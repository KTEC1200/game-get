// wide_brute.cs — 爆破 seed 0..2^25，解密 3853 字节，输出任意位置找 OggS / \x01vorbis
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

class WB
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

        long limit = args.Length > 0 ? long.Parse(args[0]) : 1L << 25;
        object gate = new object();
        int found = 0;
        Parallel.For(0, (int)limit, () => (byte[])region.Clone(), (seed, state, buf) =>
        {
            dec(seed, buf, headLen);
            for (int i = 0; i <= headLen - 4; i++)
            {
                if (buf[i] == 'O' && buf[i + 1] == 'g' && buf[i + 2] == 'g' && buf[i + 3] == 'S')
                {
                    lock (gate)
                    {
                        if (found++ < 5)
                        {
                            Console.WriteLine("OggS @ {0} seed={1}", i, seed);
                            File.WriteAllBytes(string.Format("wb_{0}_{1}.bin", seed, i), buf);
                        }
                    }
                    break;
                }
                if (buf[i] == 1 && buf[i + 1] == 'v' && buf[i + 2] == 'o' && buf[i + 3] == 'r' && buf[i + 4] == 'b' && buf[i + 5] == 'i' && buf[i + 6] == 's')
                {
                    lock (gate)
                    {
                        if (found++ < 5)
                        {
                            Console.WriteLine("vorbis @ {0} seed={1}", i, seed);
                            File.WriteAllBytes(string.Format("wb_{0}_{1}.bin", seed, i), buf);
                        }
                    }
                    break;
                }
            }
            Array.Copy(region, buf, headLen);
            return buf;
        }, _ => { });
        Console.WriteLine("done, found={0}", found);
        return 0;
    }
}
