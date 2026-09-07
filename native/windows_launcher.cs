using System;
using System.Diagnostics;
using System.IO;
using System.Web.Script.Serialization;

public class LauncherConfig { public string python; public string script; }

public class Program {
    public static int Main(string[] args) {
        try {
            string directory = AppDomain.CurrentDomain.BaseDirectory;
            string raw = File.ReadAllText(Path.Combine(directory, "launcher.json"));
            LauncherConfig config = new JavaScriptSerializer().Deserialize<LauncherConfig>(raw);
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = config.python;
            info.Arguments = Quote(config.script) + " " + JoinArguments(args);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            Process child = Process.Start(info);
            Stream input = Console.OpenStandardInput();
            Stream output = Console.OpenStandardOutput();
            byte[] header = ReadExact(input, 4);
            int length = BitConverter.ToInt32(header, 0);
            if (length < 0 || length > 65536) throw new InvalidDataException("Invalid message length.");
            byte[] body = ReadExact(input, length);
            child.StandardInput.BaseStream.Write(header, 0, header.Length);
            child.StandardInput.BaseStream.Write(body, 0, body.Length);
            child.StandardInput.Close();
            child.StandardOutput.BaseStream.CopyTo(output);
            output.Flush();
            child.WaitForExit();
            return child.ExitCode;
        } catch (Exception error) {
            Console.Error.WriteLine(error.ToString());
            return 1;
        }
    }

    private static byte[] ReadExact(Stream stream, int length) {
        byte[] result = new byte[length];
        int offset = 0;
        while (offset < length) {
            int read = stream.Read(result, offset, length - offset);
            if (read == 0) throw new EndOfStreamException();
            offset += read;
        }
        return result;
    }

    private static string JoinArguments(string[] args) {
        string result = "";
        foreach (string arg in args) result += (result.Length == 0 ? "" : " ") + Quote(arg);
        return result;
    }

    private static string Quote(string value) {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
