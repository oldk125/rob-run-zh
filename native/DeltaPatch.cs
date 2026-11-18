using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace RobRunZh
{
    // BSDIFF control/difference semantics, in a bounded standard-library gzip container.
    public static class NativeDelta
    {
        private const int MaxBytes = 256 * 1024 * 1024;
        private static readonly byte[] Magic = Encoding.ASCII.GetBytes("RRZHDF1\0");

        public static byte[] Apply(byte[] oldBytes, byte[] patchBytes)
        {
            if (oldBytes == null || patchBytes == null) throw new ArgumentNullException();
            if (oldBytes.Length > MaxBytes || patchBytes.Length < 42 || patchBytes.Length > MaxBytes)
                throw Invalid("差分输入长度无效。");
            for (int i = 0; i < Magic.Length; i++)
                if (patchBytes[i] != Magic[i]) throw Invalid("差分格式不受支持。");
            int rawLength = Length(patchBytes, 8);
            int gzipLength = Length(patchBytes, 16);
            if (rawLength < 32 || gzipLength != patchBytes.Length - 24 || gzipLength < 18)
                throw Invalid("差分容器长度不匹配。");
            // The converter writes a single gzip member without optional headers.
            if (patchBytes[24] != 31 || patchBytes[25] != 139 || patchBytes[26] != 8 || patchBytes[27] != 0)
                throw Invalid("差分压缩头无效。");
            if (BitConverter.ToUInt32(patchBytes, patchBytes.Length - 4) != (uint)rawLength)
                throw Invalid("差分压缩长度不匹配。");

            byte[] raw = new byte[rawLength];
            using (MemoryStream input = new MemoryStream(patchBytes, 24, gzipLength, false))
            using (GZipStream gzip = new GZipStream(input, CompressionMode.Decompress))
            {
                int done = 0;
                while (done < raw.Length)
                {
                    int count = gzip.Read(raw, done, raw.Length - done);
                    if (count == 0) throw Invalid("差分数据不完整。");
                    done += count;
                }
                if (gzip.ReadByte() != -1) throw Invalid("差分含多余数据。");
            }

            int newSize = Length(raw, 0);
            int controlLength = Length(raw, 8);
            int diffLength = Length(raw, 16);
            int extraLength = Length(raw, 24);
            if (controlLength % 24 != 0 || 32L + controlLength + diffLength + extraLength != rawLength)
                throw Invalid("差分区块长度无效。");
            if ((long)diffLength + extraLength != newSize)
                throw Invalid("差分输出长度无效。");

            byte[] output = new byte[newSize];
            int control = 32;
            int diff = control + controlLength;
            int diffEnd = diff + diffLength;
            int extra = diffEnd;
            int written = 0;
            long oldPosition = 0;
            while (written < output.Length)
            {
                if (control > 32 + controlLength - 24) throw Invalid("差分控制区块不完整。");
                long add = SignedMagnitude(raw, control);
                long copy = SignedMagnitude(raw, control + 8);
                long seek = SignedMagnitude(raw, control + 16);
                control += 24;
                if (add < 0 || copy < 0 || add + copy <= 0 || add > output.Length - written
                    || copy > output.Length - written - add || add > diffEnd - diff || copy > rawLength - extra)
                    throw Invalid("差分控制指令越界。");
                long afterAdd = Position(oldPosition, add);
                for (int i = 0; i < add; i++)
                {
                    long index = oldPosition + i; // afterAdd was checked, so this cannot overflow.
                    int previous = index >= 0 && index < oldBytes.Length ? oldBytes[(int)index] : 0;
                    output[written + i] = unchecked((byte)(raw[diff + i] + previous));
                }
                diff += (int)add;
                written += (int)add;
                Buffer.BlockCopy(raw, extra, output, written, (int)copy);
                extra += (int)copy;
                written += (int)copy;
                oldPosition = Position(afterAdd, seek);
            }
            if (control != 32 + controlLength || diff != diffEnd || extra != rawLength)
                throw Invalid("差分区块存在未使用数据。");
            return output;
        }

        private static int Length(byte[] bytes, int position)
        {
            long value = BitConverter.ToInt64(bytes, position);
            if (value < 0 || value > MaxBytes) throw Invalid("差分长度超出限制。");
            return (int)value;
        }

        private static long SignedMagnitude(byte[] bytes, int position)
        {
            long value = bytes[position + 7] & 127;
            for (int i = 6; i >= 0; i--) value = (value << 8) | bytes[position + i];
            return (bytes[position + 7] & 128) == 0 ? value : -value;
        }

        private static long Position(long value, long offset)
        {
            if ((offset > 0 && value > long.MaxValue - offset)
                || (offset < 0 && value < long.MinValue - offset))
                throw Invalid("差分原始位置溢出。");
            return value + offset;
        }

        private static InvalidDataException Invalid(string message)
        {
            return new InvalidDataException(message);
        }
    }
}
