// cs2_key_brute.cs — 爆破 CatSystem2 main_key：
//   约束: byteSum(MT(main_key+3).rand()) % 52 == 2 且 byteSum(MT(main_key+5).rand()) % 52 == 2
//   全验: 9 个条目名以各自 k0=byteSum(MT(main_key+i).rand()) 解出后 全可读+单点+小写扩展
using System;
using System.IO;
using System.Threading.Tasks;

class KB
{
    struct MT
    {
        public uint[] mt; public int mti;
        public MT(uint seed)
        {
            mt = new uint[624]; mti = 624;
            for (int i = 0; i < 624; i++)
            {
                uint upper = seed & 0xFFFF0000;
                seed = 69069u * seed + 1;
                mt[i] = upper | ((seed & 0xFFFF0000) >> 16);
                seed = 69069u * seed + 1;
            }
        }
        public uint Rand()
        {
            if (mti >= 624)
            {
                uint[] m = mt;
                uint y;
                int kk;
                for (kk = 0; kk < 227; kk++)
                {
                    y = (m[kk] & 0x80000000) | (m[kk + 1] & 0x7FFFFFFF);
                    m[kk] = m[kk + 397] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                }
                for (; kk < 623; kk++)
                {
                    y = (m[kk] & 0x80000000) | (m[kk + 1] & 0x7FFFFFFF);
                    m[kk] = m[kk - 227] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                }
                y = (m[623] & 0x80000000) | (m[0] & 0x7FFFFFFF);
                m[623] = m[396] ^ (y >> 1) ^ ((y & 1) != 0 ? 0x9908B0DFu : 0);
                mti = 0;
            }
            uint r = mt[mti++];
            r ^= r >> 11;
            r ^= (r << 7) & 0x9D2C5680;
            r ^= (r << 15) & 0xEFC60000;
            r ^= r >> 18;
            return r;
        }
    }

    static int ByteSum(uint k)
    {
        return (byte)((k >> 24) + (k >> 16) + (k >> 8) + k);
    }

    static char[] alphabet = "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA".ToCharArray();

    static string Decipher(byte[] name, int k0)
    {
        int k = k0;
        var sb = new System.Text.StringBuilder();
        for (int i = 0; i < name.Length && name[i] != 0; i++)
        {
            int idx = Array.IndexOf(alphabet, (char)name[i]);
            if (idx != -1)
            {
                int j = idx - k % 0x34;
                if (j < 0) j += 0x34;
                sb.Append(alphabet[0x33 - j]);
            }
            else sb.Append((char)name[i]);
            k = (k + 1) & 0xFF;
        }
        return sb.ToString();
    }

    static int Main(string[] args)
    {
        string root = FindRoot();
        byte[][] names = new byte[9][];
        using (var fs = File.OpenRead(Path.Combine(root, "mot.int")))
        {
            var br = new BinaryReader(fs);
            fs.Position = 4;
            int count = br.ReadInt32();
            for (int i = 1; i <= 9; i++)
            {
                fs.Position = 8 + i * 0x48;
                names[i - 1] = br.ReadBytes(0x40);
            }
        }
        Console.WriteLine("loaded mot.int names");
        long limit = args.Length > 0 ? long.Parse(args[0]) : int.MaxValue;
        object gate = new object();
        int found = 0;
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Parallel.For(0, (int)Math.Min(limit, int.MaxValue), () => 0, (seed, state, dummy) =>
        {
            uint mk = (uint)seed;
            var t3 = new MT(mk + 3);
            if (ByteSum(t3.Rand()) % 52 != 2) return 0;
            var t5 = new MT(mk + 5);
            if (ByteSum(t5.Rand()) % 52 != 2) return 0;
            // 全验 9 个名字
            bool allok = true;
            for (int i = 1; i <= 9 && allok; i++)
            {
                var t = new MT(mk + (uint)i);
                int k0 = ByteSum(t.Rand());
                string nm = Decipher(names[i - 1], k0);
                int dot = nm.LastIndexOf('.');
                if (dot <= 0 || dot != nm.Length - 4) { allok = false; break; }
                string ext = nm.Substring(dot + 1);
                foreach (char c in nm)
                    if (c < 32 || c > 126) { allok = false; break; }
                if (!allok) break;
                foreach (char c in ext)
                    if (c < 'a' || c > 'z') { allok = false; break; }
            }
            if (allok)
            {
                lock (gate)
                {
                    if (found++ < 5)
                    {
                        Console.WriteLine("HIT main_key = {0} (0x{0:X})", mk);
                        for (int i = 1; i <= 9; i++)
                        {
                            var t = new MT(mk + (uint)i);
                            Console.WriteLine("   " + Decipher(names[i - 1], ByteSum(t.Rand())));
                        }
                    }
                }
                if (found >= 5) state.Stop();
            }
            return 0;
        }, _ => { });
        sw.Stop();
        Console.WriteLine("done found={0} elapsed={1:F0}s", found, sw.Elapsed.TotalSeconds);
        return 0;
    }

    static string FindRoot()
    {
        foreach (var n in Directory.GetDirectories(@"D:\HY"))
            foreach (var s in Directory.GetDirectories(n))
                if (s.Contains("2+") && File.Exists(Path.Combine(s, "mot.int")))
                    return s;
        return null;
    }
}
