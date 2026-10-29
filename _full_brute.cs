// full_brute.cs — 爆破真实解密函数 (seed ∈ [0, 2^31))，OggS/vorbis 任意位置命中即停
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

class FB
{
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr hFile, uint flags);
    delegate void DecryptDel(int seed, byte[] data, int len);

    static string FindRoot()
    {
        foreach (var n in Directory.GetDirectories(@"D:\HY"))
            if (Directory.Exists(Path.Combine(n, "res", "s")) && File.Exists(Path.Combine(n, "ExHIBIT.ini")))
                return n;
        return null;
    }

    static int Main(string[] args)
    {
        string root = FindRoot();
        IntPtr h = LoadLibraryEx(Path.Combine(root, "resident.dll"), IntPtr.Zero, 0x8);
        if (h == IntPtr.Zero) { Console.WriteLine("load fail {0}", Marshal.GetLastWin32Error()); return 1; }
        long b = h.ToInt64();
        var dec = (DecryptDel)Marshal.GetDelegateForFunctionPointer(new IntPtr(b + 0x1F3ED0), typeof(DecryptDel));

        byte[] file = File.ReadAllBytes(Path.Combine(root, "res", "s", "m", "m01.ogg"));
        int headLen = 3853;
        byte[] region = new byte[headLen];
        Array.Copy(file, region, headLen);

        long limit = args.Length > 0 ? long.Parse(args[0]) : int.MaxValue;
        object gate = new object();
        int found = 0;
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Parallel.For(0, (int)limit, () => (byte[])region.Clone(), (seed, state, buf) =>
        {
            dec(seed, buf, headLen);
            for (int i = 0; i <= headLen - 7; i++)
            {
                bool og = buf[i] == 'O' && buf[i + 1] == 'g' && buf[i + 2] == 'g' && buf[i + 3] == 'S';
                bool vb = buf[i] == 1 && buf[i + 1] == 'v' && buf[i + 2] == 'o' && buf[i + 3] == 'r' && buf[i + 4] == 'b' && buf[i + 5] == 'i' && buf[i + 6] == 's';
                if (og || vb)
                {
                    lock (gate)
                    {
                        if (found++ < 8)
                        {
                            Console.WriteLine("{0} @ {1} seed={2} (0x{2:X})", og ? "OggS" : "vorbis", i, seed);
                            File.WriteAllBytes(string.Format("fb_{0}.bin", seed), buf);
                        }
                    }
                    if (found >= 8) state.Stop();
                    break;
                }
            }
            Array.Copy(region, buf, headLen);
            return buf;
        }, _ => { });
        sw.Stop();
        Console.WriteLine("done found={0} elapsed={1:F1}s", found, sw.Elapsed.TotalSeconds);
        return 0;
    }
}
