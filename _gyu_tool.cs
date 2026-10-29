// gyu_tool.cs — ExHIBIT .gyu 批量解码器（算法照抄 GARbro-Mod:
//   ArcFormats/ExHibit/ImageGYU.cs + ArcFormats/{MersenneTwister,LzssStream,BitStream}.cs）
// 用系统自带 csc.exe 编译: csc /r:System.Drawing.dll gyu_tool.cs
// 用法: gyu_tool <root> <outdir>
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading.Tasks;

static class Gytool
{
    // ---- MersenneTwister.cs（GARbro 自定义 SRand + 标准 MT19937 刷新/ tempering）----
    class MT
    {
        uint[] mt = new uint[624];
        int mti = 624;
        public MT(uint seed) { SRand(seed); }
        public void SRand(uint seed)
        {
            for (mti = 0; mti < mt.Length; ++mti)
            {
                uint upper = seed & 0xffff0000;
                seed = 69069 * seed + 1;
                mt[mti] = upper | (seed & 0xffff0000) >> 16;
                seed = 69069 * seed + 1;
            }
        }
        public uint Rand()
        {
            uint y;
            if (mti >= 624)
            {
                int kk;
                for (kk = 0; kk < 624 - 397; kk++)
                {
                    y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7FFFFFFF);
                    mt[kk] = mt[kk + 397] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                }
                for (; kk < 623; kk++)
                {
                    y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7FFFFFFF);
                    mt[kk] = mt[kk + 397 - 624] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                }
                y = (mt[623] & 0x80000000) | (mt[0] & 0x7FFFFFFF);
                mt[623] = mt[396] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                mti = 0;
            }
            y = mt[mti++];
            y ^= y >> 11;
            y ^= (y << 7) & 0x9D2C5680;
            y ^= (y << 15) & 0xEFC60000;
            y ^= y >> 18;
            return y;
        }
    }

    static void Deobfuscate(byte[] data, uint key)
    {
        var mt = new MT(key);
        for (int n = 0; n < 10; ++n)
        {
            uint i1 = mt.Rand() % (uint)data.Length;
            uint i2 = mt.Rand() % (uint)data.Length;
            byte tmp = data[i1]; data[i1] = data[i2]; data[i2] = tmp;
        }
    }

    // ---- MsbBitStream.cs（字节与位共享同一游标——对应原实现里 mem/mem 的关系）----
    class MsbBits
    {
        byte[] buf; int pos; int cached; int acc;
        public MsbBits(byte[] b, int start) { buf = b; pos = start; cached = 0; acc = 0; }
        public int ReadByte()
        {
            if (pos >= buf.Length) return -1;
            return buf[pos++];
        }
        public int GetBits(int count)
        {
            while (cached < count)
            {
                int b = ReadByte();
                if (-1 == b) return -1;
                acc = (acc << 8) | b;
                cached += 8;
            }
            int mask = (1 << count) - 1;
            cached -= count;
            return (acc >> cached) & mask;
        }
        public int NextBit() { return GetBits(1); }
    }

    // ---- LzssStream.cs（FrameSize 0x1000 / fill 0 / init 0xFEE / flag 位 LSB 先行）----
    static int Lzss(byte[] src, int srcPos, int srcLen, byte[] dst, int dstLen)
    {
        var frame = new byte[0x1000];
        int fpos = 0xFEE;
        const int mask = 0xFFF;
        int ip = srcPos, iend = srcPos + srcLen, op = 0;
        for (; ; )
        {
            if (ip >= iend) break;
            int ctl = src[ip++];
            for (int bit = 1; bit != 0x100 && ip < iend && op < dstLen; bit <<= 1)
            {
                if ((ctl & bit) != 0)
                {
                    byte b = src[ip++];
                    frame[fpos++ & mask] = b;
                    if (op < dstLen) dst[op++] = b; else return op;
                }
                else
                {
                    if (ip + 2 > iend) return op;
                    int lo = src[ip++], hi = src[ip++];
                    int offset = ((hi & 0xf0) << 4) | lo;
                    for (int count = 3 + (hi & 0xF); count != 0; --count)
                    {
                        byte v = frame[offset++ & mask];
                        frame[fpos++ & mask] = v;
                        if (op < dstLen) dst[op++] = v; else return op;
                    }
                }
            }
        }
        return op;
    }

    // ---- UnpackGyu（ImageGYU.cs：跳过前 4 字节 + 首字面量 + MSB 位流；字节/位共享游标）----
    static int UnpackGyu(byte[] packed, byte[] dst)
    {
        var st = new MsbBits(packed, 4);
        int dst_n = dst.Length, d = 0;
        int first = st.ReadByte();
        if (first < 0) return 0;
        dst[d++] = (byte)first;
        while (d < dst_n)
        {
            int b = st.NextBit();
            if (-1 == b) break;
            if (1 == b)
            {
                int v = st.ReadByte();
                if (-1 == v) break;
                dst[d++] = (byte)v;
                continue;
            }
            int count, offset;
            if (1 == st.NextBit())
            {
                int hi = st.ReadByte(), lo = st.ReadByte();
                if (-1 == hi || -1 == lo) break;
                count = (hi << 8) | lo;
                offset = -0x2000 | (count >> 3);
                count &= 7;
                if (0 != count) ++count;
                else { count = st.ReadByte(); if (0 == count) break; }
            }
            else
            {
                count = 1 + st.GetBits(2);
                int o = st.ReadByte();
                if (-1 == o) break;
                offset = -0x100 | o;
            }
            ++count;
            for (int i = 0; i < count && d < dst_n; ++i, ++d)
                dst[d] = dst[d + offset];
        }
        return d;
    }

    class Meta
    {
        public int Flags, Mode, Bpp, DataSize, AlphaSize, PaletteSize;
        public uint Key; public int W, H;
    }

    static Meta ReadMeta(byte[] b)
    {
        var m = new Meta();
        m.Flags = b[4] | (b[5] << 8);
        m.Mode = b[6] | (b[7] << 8);
        m.Key = (uint)(b[8] | (b[9] << 8) | (b[10] << 16) | (b[11] << 24));
        m.Bpp = BitConverter.ToInt32(b, 12);
        m.W = (int)BitConverter.ToUInt32(b, 16);
        m.H = (int)BitConverter.ToUInt32(b, 20);
        m.DataSize = BitConverter.ToInt32(b, 24);
        m.AlphaSize = BitConverter.ToInt32(b, 28);
        m.PaletteSize = BitConverter.ToInt32(b, 32);
        return m;
    }

    // 返回 BGRA 自上而下像素数组
    static byte[] Decode(byte[] file, Meta m, string name)
    {
        int stride = (m.W * m.Bpp / 8 + 3) & ~3;
        if (8 == m.Bpp && 0 == m.PaletteSize) throw new InvalidDataException("8bpp 无调色板");
        int p = 0x24;
        Color[] pal = null;
        if (0 != m.PaletteSize)
        {
            int ncol = Math.Min(m.PaletteSize, 0x100);
            pal = new Color[ncol];
            for (int i = 0; i < ncol; ++i)
                pal[i] = Color.FromArgb(255, file[p + 4 * i + 2], file[p + 4 * i + 1], file[p + 4 * i]);
            p += 4 * ncol;
        }
        var packed = new byte[m.DataSize];
        Array.Copy(file, p, packed, 0, m.DataSize);
        p += m.DataSize;

        if (0xFFFFFFFF != m.Key) Deobfuscate(packed, m.Key);

        byte[] body;
        if (0x0100 == m.Mode) body = packed;
        else if (0x0800 == m.Mode)
        {
            body = new byte[stride * m.H];
            int n = UnpackGyu(packed, body);
            if (n != body.Length) throw new InvalidDataException(string.Format("GyuLZ 输出不足 {0}/{1}", n, body.Length));
        }
        else
        {
            body = new byte[stride * m.H];
            int n = Lzss(packed, 0, packed.Length, body, body.Length);
            if (n != body.Length) throw new InvalidDataException(string.Format("LZSS 输出不足 {0}/{1}", n, body.Length));
        }

        byte[] pixels;
        int w = m.W, h = m.H;
        if (0 != m.AlphaSize)
        {
            int alpha_stride = (w + 3) & ~3;
            byte[] alpha;
            if (m.AlphaSize == alpha_stride * h)
            {
                alpha = new byte[m.AlphaSize];
                Array.Copy(file, p, alpha, 0, m.AlphaSize);
            }
            else
            {
                alpha = new byte[alpha_stride * h];
                int n = Lzss(file, p, file.Length - p, alpha, alpha.Length);
                if (n != alpha.Length) throw new InvalidDataException(string.Format("alpha LZSS 不足 {0}/{1}", n, alpha.Length));
            }
            bool extend = 3 != m.Flags;
            pixels = new byte[w * 4 * h];
            for (int y = 0; y < h; ++y)
            {
                int src = y * stride, aline = y * alpha_stride, dst = y * w * 4;
                for (int x = 0; x < w; ++x)
                {
                    if (8 == m.Bpp)
                    {
                        var c = pal[body[src++]];
                        pixels[dst++] = c.B; pixels[dst++] = c.G; pixels[dst++] = c.R;
                    }
                    else
                    {
                        pixels[dst++] = body[src++]; pixels[dst++] = body[src++]; pixels[dst++] = body[src++];
                    }
                    int a = alpha[aline + x];
                    if (extend) a = a >= 0x10 ? 0xFF : a * 0x10;
                    pixels[dst++] = (byte)a;
                }
            }
        }
        else
        {
            pixels = new byte[w * 4 * h];
            for (int y = 0; y < h; ++y)
            {
                int src = y * stride, dst = y * w * 4;
                for (int x = 0; x < w; ++x)
                {
                    if (8 == m.Bpp)
                    {
                        var c = pal[body[src++]];
                        pixels[dst++] = c.B; pixels[dst++] = c.G; pixels[dst++] = c.R; pixels[dst++] = 255;
                    }
                    else if (24 == m.Bpp)
                    {
                        pixels[dst++] = body[src++]; pixels[dst++] = body[src++]; pixels[dst++] = body[src++]; pixels[dst++] = 255;
                    }
                    else // 32bpp Bgr32
                    {
                        pixels[dst++] = body[src++]; pixels[dst++] = body[src++]; pixels[dst++] = body[src++]; src++; pixels[dst++] = 255;
                    }
                }
            }
        }
        // CreateFlipped：原数据自下而上 → 翻转为自上而下
        int row = w * 4;
        var flip = new byte[row * h];
        for (int y = 0; y < h; ++y)
            Array.Copy(pixels, y * row, flip, (h - 1 - y) * row, row);
        return flip;
    }

    static int Main(string[] args)
    {
        if (args.Length < 2) { Console.WriteLine("usage: gyu_tool <root> <outdir>"); return 2; }
        var root = Path.GetFullPath(args[0]);
        var outRoot = Path.GetFullPath(args[1]);
        var files = new List<string>();
        foreach (var f in Directory.EnumerateFiles(root, "*.gyu", SearchOption.AllDirectories))
            files.Add(f);
        files.Sort(StringComparer.OrdinalIgnoreCase);
        Console.WriteLine("found {0} .gyu", files.Count);

        int ok = 0, fail = 0;
        var fails = new List<string>();
        Parallel.For(0, files.Count, i =>
        {
            string f = files[i];
            try
            {
                var data = File.ReadAllBytes(f);
                if (data.Length < 0x24 || data[0] != 'G' || data[1] != 'Y' || data[2] != 'U' || data[3] != 0x1A)
                    throw new InvalidDataException("非 GYU 签名");
                var m = ReadMeta(data);
                var px = Decode(data, m, Path.GetFileNameWithoutExtension(f));
                string rel = f.Substring(root.Length).TrimStart('\\', '/');
                string dst = Path.Combine(outRoot, rel);
                dst = Path.ChangeExtension(dst, ".png");
                Directory.CreateDirectory(Path.GetDirectoryName(dst));
                using (var bmp = new Bitmap(m.W, m.H, PixelFormat.Format32bppArgb))
                {
                    var bd = bmp.LockBits(new Rectangle(0, 0, m.W, m.H), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
                    System.Runtime.InteropServices.Marshal.Copy(px, 0, bd.Scan0, px.Length);
                    bmp.UnlockBits(bd);
                    bmp.Save(dst, ImageFormat.Png);
                }
                InterlockedAdd(ref ok);
            }
            catch (Exception ex)
            {
                lock (fails)
                {
                    fail++;
                    if (fails.Count < 40) fails.Add(string.Format("{0} :: {1}", Path.GetFileName(f), ex.Message));
                }
            }
        });
        Console.WriteLine("ok {0}  fail {1}", ok, fail);
        foreach (var s in fails) Console.WriteLine("  FAIL " + s);
        return fail == 0 ? 0 : 1;
    }

    static int _ok;
    static void InterlockedAdd(ref int v) { System.Threading.Interlocked.Increment(ref v); }
}
