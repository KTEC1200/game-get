// hg3_tool.cs — CatSystem2 HG-3 批量解码（算法照抄 GARbro-Mod ImageHG3.cs，
// 经 Python 慢速参考版逐字节验证正确后移植）
// 编译: csc /r:System.Drawing.dll hg3_tool.cs    用法: hg3_tool <root> <outdir>
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Compression;
using System.Threading.Tasks;

class Hg3Tool
{
    static byte[] Inflate(byte[] src, int off, int len, int expect)
    {
        // zlib 流：跳过 2 字节头
        var ms = new MemoryStream(src, off + 2, len - 2);
        var df = new DeflateStream(ms, CompressionMode.Decompress);
        var outBuf = new byte[expect];
        int got = 0, r;
        while (got < expect && (r = df.Read(outBuf, got, expect - got)) > 0) got += r;
        df.Dispose();
        if (got != expect) throw new InvalidDataException(string.Format("inflate {0}/{1}", got, expect));
        return outBuf;
    }

    class Bits
    {
        byte[] b; int pos, bit, cur;
        public Bits(byte[] buf) { b = buf; }
        public int NextBit()
        {
            if (bit == 0)
            {
                if (pos >= b.Length) throw new EndOfStreamException();
                cur = b[pos++]; bit = 8;
            }
            int r = cur & 1;
            cur >>= 1; bit--;
            return r;
        }
        public int GetBitCount()
        {
            int n = 0;
            while (NextBit() == 0) { if (++n >= 0x20) throw new InvalidDataException("ovf"); }
            int v = 1;
            for (int i = 0; i < n; i++) v = (v << 1) | NextBit();
            return v;
        }
    }

    static byte ConvertValue(byte val)
    {
        bool carry = (val & 1) != 0;
        byte v = (byte)(val >> 1);
        return (byte)(carry ? v ^ 0xFF : v);
    }

    static byte[] ApplyDelta(byte[] pixels, int w, int h, int psize)
    {
        var table = new uint[4, 0x100];
        for (uint i = 0; i < 0x100; i++)
        {
            uint val = i & 0xC0;
            val = (val << 6) | (i & 0x30);
            val = (val << 6) | (i & 0x0C);
            val = (val << 6) | (i & 0x03);
            table[0, i] = val << 6;
            table[1, i] = val << 4;
            table[2, i] = val << 2;
            table[3, i] = val;
        }
        int planeSize = pixels.Length / 4;
        int p1 = planeSize, p2 = planeSize * 2, p3 = planeSize * 3;
        var output = new byte[pixels.Length];
        int i0 = 0, i1 = planeSize, i2 = planeSize * 2, i3 = planeSize * 3, dst = 0;
        while (dst < output.Length)
        {
            uint val = table[0, pixels[i0++]] | table[1, pixels[i1++]] | table[2, pixels[i2++]] | table[3, pixels[i3++]];
            output[dst++] = ConvertValue((byte)val);
            output[dst++] = ConvertValue((byte)(val >> 8));
            output[dst++] = ConvertValue((byte)(val >> 16));
            output[dst++] = ConvertValue((byte)(val >> 24));
        }
        int stride = w * psize;
        for (int x = psize; x < stride; x++)
            output[x] += output[x - psize];
        int prev = 0;
        for (int y = 1; y < h; y++)
        {
            int line = prev + stride;
            for (int x = 0; x < stride; x++)
                output[line + x] += output[prev + x];
            prev = line;
        }
        return output;
    }

    static byte[] RleDecode(byte[] pixelsRaw, byte[] ctlRaw)
    {
        var bits = new Bits(ctlRaw);
        bool copy = bits.NextBit() != 0;
        int outputSize = bits.GetBitCount();
        var output = new byte[outputSize];
        int src = 0, dst = 0;
        while (dst < outputSize)
        {
            int count = bits.GetBitCount();
            if (copy)
            {
                Buffer.BlockCopy(pixelsRaw, src, output, dst, count);
                src += count;
            }
            dst += count;
            copy = !copy;
        }
        return output;
    }

    static byte[] DecodeImg0000(byte[] data, int imgStart, int w, int h, int bpp, out int stride)
    {
        int psize = bpp / 8;
        stride = w * psize;
        int pd = BitConverter.ToInt32(data, imgStart + 0x18);
        int ds = BitConverter.ToInt32(data, imgStart + 0x1C);
        int pc = BitConverter.ToInt32(data, imgStart + 0x20);
        int csz = BitConverter.ToInt32(data, imgStart + 0x24);
        int dstart = imgStart + 0x28;
        var pixelsRaw = Inflate(data, dstart, pd, ds);
        var ctlRaw = Inflate(data, dstart + pd, pc, csz);
        var rle = RleDecode(pixelsRaw, ctlRaw);
        return ApplyDelta(rle, w, h, psize);
    }

    static bool IsHg3Magic(string path)
    {
        try
        {
            using (var fs = File.OpenRead(path))
            {
                var b = new byte[4];
                if (fs.Read(b, 0, 4) != 4) return false;
                return b[0] == 'H' && b[1] == 'G' && b[2] == '-' && b[3] == '3';
            }
        }
        catch { return false; }
    }

    static Bitmap DecodeFile(byte[] data)
    {
        if (data[0] != 'H' || data[1] != 'G' || data[2] != '-' || data[3] != '3')
            throw new InvalidDataException("非 HG-3");
        if (BitConverter.ToUInt32(data, 4) != 0x0C)
            throw new InvalidDataException("版本字段");
        if (data[0x14] != 's' || data[0x15] != 't' || data[0x16] != 'd')
            throw new InvalidDataException("无 stdinfo");
        int w = (int)BitConverter.ToUInt32(data, 0x24);
        int h = (int)BitConverter.ToUInt32(data, 0x28);
        int bpp = BitConverter.ToInt32(data, 0x2C);
        if (bpp != 32 && bpp != 24) throw new InvalidDataException("BPP " + bpp);
        // 分节链从 0x14
        int pos = 0x14, imgStart = -1;
        string imgName = null;
        for (int step = 0; step < 64; step++)
        {
            var name = new byte[8];
            Array.Copy(data, pos, name, 0, 8);
            int size = BitConverter.ToInt32(data, pos + 8);
            var s = System.Text.Encoding.ASCII.GetString(name).TrimEnd('\0');
            if (s == "img0000" || s == "img_jpg") { imgStart = pos; imgName = s; break; }
            if (size == 0) throw new InvalidDataException("无 img 节");
            pos += size;
        }
        if (imgStart < 0) throw new InvalidDataException("无 img 节");
        if (imgName == "img0000")
        {
            // ApplyDelta 对 24/32bpp 同构（4 等分位转置，GARbro 同款）；
            // 24bpp 唯一区别: psize=3、BGR24 落盘。row 必须按 psize 算，硬编码 w*4 会越界。
            int psize = bpp / 8;
            int stride;
            byte[] px = DecodeImg0000(data, imgStart, w, h, bpp, out stride);
            int row = w * psize;
            var flip = new byte[row * h];
            for (int y = 0; y < h; y++)
                Array.Copy(px, y * row, flip, (h - 1 - y) * row, row);
            var fmt = psize == 4 ? PixelFormat.Format32bppArgb : PixelFormat.Format24bppRgb;
            var bmp = new Bitmap(w, h, fmt);
            var bd = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, fmt);
            System.Runtime.InteropServices.Marshal.Copy(flip, 0, bd.Scan0, flip.Length);
            bmp.UnlockBits(bd);
            return bmp;
        }
        throw new InvalidDataException("img 分节类型 " + imgName + " 暂不支持");
    }

    static int Main(string[] args)
    {
        if (args.Length < 2) { Console.WriteLine("usage: hg3_tool <root> <outdir>"); return 2; }
        var root = Path.GetFullPath(args[0]);
        var outRoot = Path.GetFullPath(args[1]);
        var files = new List<string>();
        foreach (var f in Directory.EnumerateFiles(root, "*.*", SearchOption.AllDirectories))
        {
            if (IsHg3Magic(f)) files.Add(f);
        }
        files.Sort(StringComparer.OrdinalIgnoreCase);
        Console.WriteLine("found {0}", files.Count);
        int ok = 0, fail = 0;
        var fails = new List<string>();
        Parallel.For(0, files.Count, i =>
        {
            try
            {
                byte[] data = File.ReadAllBytes(files[i]);
                using (var bmp = DecodeFile(data))
                {
                    string rel = files[i].Substring(root.Length).TrimStart('\\', '/');
                    string dst = Path.Combine(outRoot, rel);
                    dst = Path.ChangeExtension(dst, ".png");
                    Directory.CreateDirectory(Path.GetDirectoryName(dst));
                    bmp.Save(dst, ImageFormat.Png);
                }
                System.Threading.Interlocked.Increment(ref ok);            }
            catch (Exception ex)
            {
                lock (fails)
                {
                    fail++;
                    if (fails.Count < 15) fails.Add(Path.GetFileName(files[i]) + " :: " + ex.Message);
                }
            }
        });
        Console.WriteLine("ok {0} fail {1}", ok, fail);
        foreach (var s in fails) Console.WriteLine("  FAIL " + s);
        return fail == 0 ? 0 : 1;
    }
}
