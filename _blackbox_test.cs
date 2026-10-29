// blackbox_test.cs — 直接调用 resident.dll 的 0x101f3ed0 (seed, data, len) 解密函数
// 用法: blackbox_test <headLen> [seed上限]
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

class BB
{
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr hFile, uint flags);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    delegate void DecryptDel(int seed, byte[] data, int len);

    static string FindRoot()
    {
        foreach (var n in Directory.GetDirectories(@"D:\HY"))
        {
            if (File.Exists(Path.Combine(n, "res", "s")) || Directory.Exists(Path.Combine(n, "res", "s")))
                if (File.Exists(Path.Combine(n, "ExHIBIT.ini")))
                    return n;
        }
        return null;
    }

    static int Main(string[] args)
    {
        int headLen = int.Parse(args[0]);
        int maxSeed = args.Length > 1 ? int.Parse(args[1]) : 0x40000;

        string root = FindRoot();
        if (root == null) { Console.WriteLine("root not found"); return 1; }
        Console.WriteLine("root = {0}", root);
        string dll = Path.Combine(root, "resident.dll");
        string ogg = Path.Combine(root, "res", "s", "m", "m01.ogg");

        SetDllDirectory(root);
        IntPtr h = LoadLibraryEx(dll, IntPtr.Zero, 0x8);
        if (h == IntPtr.Zero) { Console.WriteLine("LoadLibrary failed: " + Marshal.GetLastWin32Error()); return 1; }
        Console.WriteLine("base = 0x{0:X}", h.ToInt64());
        IntPtr fn = new IntPtr(h.ToInt64() + 0x1F3ED0);
        var dec = (DecryptDel)Marshal.GetDelegateForFunctionPointer(fn, typeof(DecryptDel));

        byte[] file = File.ReadAllBytes(ogg);
        byte[] region = new byte[headLen];
        Array.Copy(file, region, Math.Min(headLen, file.Length));

        for (int seed = 0; seed < maxSeed; seed++)
        {
            byte[] buf = (byte[])region.Clone();
            dec(seed, buf, headLen);
            if (buf[0] == 'O' && buf[1] == 'g' && buf[2] == 'g' && buf[3] == 'S')
            {
                Console.WriteLine("HIT seed={0} (0x{0:X})", seed);
                var hexs = new StringBuilder();
                for (int i = 0; i < 64; i++) hexs.AppendFormat("{0:x2} ", buf[i]);
                Console.WriteLine(hexs.ToString());
                File.WriteAllBytes(ogg + ".dec", buf);
                return 0;
            }
            if (seed % 0x10000 == 0 && seed > 0) Console.WriteLine("... {0:x}", seed);
        }
        Console.WriteLine("no hit in 0..{0}", maxSeed - 1);
        return 2;
    }
}
