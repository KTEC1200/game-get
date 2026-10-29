// blackbox2.cs — 组合测试: 种子=文件前4字节(LE/BE), 数据起点{0,4}, 分页{单次,两页}, 函数{ROR,ROL}
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

class BB2
{
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr hFile, uint flags);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    delegate void DecryptDel(int seed, byte[] data, int len);

    static string FindRoot()
    {
        foreach (var n in Directory.GetDirectories(@"D:\HY"))
            if (Directory.Exists(Path.Combine(n, "res", "s")) && File.Exists(Path.Combine(n, "ExHIBIT.ini")))
                return n;
        return null;
    }

    // 在 ROR 函数(0x1F3ED0)之前找 ROL 孪生：搜 .text 中 `rol byte ptr [ebx], cl` 的函数起点
    // 简化：直接搜 0x101f4100-0x101f4300 区间的函数头（int3 后的 push ebp）
    static int Main(string[] args)
    {
        string root = FindRoot();
        Console.WriteLine("root = {0}", root);
        IntPtr h = LoadLibraryEx(Path.Combine(root, "resident.dll"), IntPtr.Zero, 0x8);
        if (h == IntPtr.Zero) { Console.WriteLine("LoadLibrary fail {0}", Marshal.GetLastWin32Error()); return 1; }
        long b = h.ToInt64();
        var decRor = (DecryptDel)Marshal.GetDelegateForFunctionPointer(new IntPtr(b + 0x1F3ED0), typeof(DecryptDel));

        // ROL 孪生函数地址：从 ROR 函数向后搜「popal/popfd 模板一致」的下一函数太麻烦，
        // 直接按 step5 里 ROL 站点 0x101f4209 所在函数：向后找 ret（C3）+ int3 对齐的函数尾再取下一函数头
        // 简化：先试 ROR 单函数的所有组合；ROL 需要时再加。

        byte[] file = File.ReadAllBytes(Path.Combine(root, "res", "s", "m", "m01.ogg"));
        int headLen = 3853;

        var sb = new StringBuilder();
        foreach (long seedRaw in new long[] {
            (long)(int)BitConverter.ToInt32(file, 0),            // prefix LE as int
            BitConverter.ToInt32(file, 0),                        // prefix LE as uint->int overflow? handled
            (int)BitConverter.ToUInt32(file, 0),
            (int)BitConverter.ToUInt32(new byte[]{file[3],file[2],file[1],file[0]},0) })
        {
            int seed = (int)seedRaw;
            foreach (int start in new int[] { 0, 4 })
            {
                // 单次调用
                byte[] buf = new byte[headLen + 16];
                Array.Copy(file, start, buf, 0, headLen);
                decRor(seed, buf, headLen);
                bool hit = buf[0] == 'O' && buf[1] == 'g' && buf[2] == 'g' && buf[3] == 'S';
                sb.AppendFormat("seed={0:X8} start={1} single: {2} {3}\n", seed, start, BitConverter.ToString(buf, 0, 12), hit ? "  <<< HIT" : "");
                if (hit) File.WriteAllBytes("hit_single.bin", buf);

                // 两页调用（58 + 3795），表索引各自从 0 开始
                byte[] b2 = new byte[headLen + 16];
                Array.Copy(file, start, b2, 0, headLen);
                int page0 = 58;
                decRor(seed, b2, page0);
                byte[] rest = new byte[headLen - page0];
                Array.Copy(b2, page0, rest, 0, rest.Length);
                decRor(seed, rest, rest.Length);
                Array.Copy(rest, 0, b2, page0, rest.Length);
                hit = b2[0] == 'O' && b2[1] == 'g' && b2[2] == 'g' && b2[3] == 'S';
                sb.AppendFormat("seed={0:X8} start={1} two-page: {2} {3}\n", seed, start, BitConverter.ToString(b2, 0, 12), hit ? "  <<< HIT" : "");
                if (hit) File.WriteAllBytes("hit_twopage.bin", b2);
            }
        }
        Console.Write(sb.ToString());
        return 0;
    }
}
