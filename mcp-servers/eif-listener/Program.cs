// EIF event capture for the Sourcing agent.
// Subscribes (durably) to the tenant's 3DEXPERIENCE EIF event topic and saves every
// message it receives as its own JSON file under ./events, so the exact payload of the
// "Manufacturing Item versioned" event can be inspected and later used as the agent trigger.
//
// Based on Dassault Systemes CPE EMED's EIFClientConsoleApp sample (MIT licensed):
// https://github.com/3ds-cpe-emed/3dxws.dotnet.event.samples

using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Apache.NMS;
using Apache.NMS.ActiveMQ;
using Apache.NMS.ActiveMQ.Commands;

namespace EifListener;

internal static class Program
{
    private static string _outputDir = "events";
    private static int _count;
    private static volatile bool _connected;
    private static readonly JsonSerializerOptions Pretty = new() { WriteIndented = true };

    private static int Main()
    {
        // ---- configuration -------------------------------------------------------------
        var configPath = Path.Combine(AppContext.BaseDirectory, "config.json");
        if (!File.Exists(configPath)) configPath = "config.json";
        if (!File.Exists(configPath))
        {
            Console.Error.WriteLine("config.json not found.");
            return 1;
        }

        var cfg = JsonNode.Parse(File.ReadAllText(configPath))!.AsObject();
        string jmsUrl = Get(cfg, "JmsUrl");
        string agentId = Get(cfg, "AgentId");
        string tenantId = Get(cfg, "TenantId");
        string topicName = Get(cfg, "Topic");
        _outputDir = Get(cfg, "OutputDir");
        if (string.IsNullOrWhiteSpace(_outputDir)) _outputDir = "events";
        if (string.IsNullOrWhiteSpace(topicName)) topicName = $"3dsevents.{tenantId}.3DSpace.user";

        foreach (var (name, value) in new[] { ("JmsUrl", jmsUrl), ("AgentId", agentId), ("TenantId", tenantId) })
        {
            if (string.IsNullOrWhiteSpace(value) || value.Contains('<'))
            {
                Console.Error.WriteLine($"Please fill in '{name}' in config.json.");
                return 1;
            }
        }

        // The agent secret (API key from Agent Management) is never stored in config.json.
        string? secret = Environment.GetEnvironmentVariable("EIF_AGENT_SECRET")?.Trim();
        if (string.IsNullOrEmpty(secret) && File.Exists("agent.secret"))
            secret = File.ReadAllText("agent.secret").Trim();
        if (string.IsNullOrEmpty(secret))
        {
            Console.Error.WriteLine("Agent secret missing. Set EIF_AGENT_SECRET or start via run.ps1, which prompts for it.");
            return 1;
        }

        Directory.CreateDirectory(_outputDir);
        string consumerName = $"{tenantId}-{agentId}";

        Console.WriteLine($"Broker   : {jmsUrl}");
        Console.WriteLine($"Topic    : {topicName}");
        Console.WriteLine($"Consumer : {consumerName} (durable)");
        Console.WriteLine($"Saving to: {Path.GetFullPath(_outputDir)}");
        string secretSource = Environment.GetEnvironmentVariable("EIF_AGENT_SECRET") != null ? "EIF_AGENT_SECRET" : "agent.secret";
        Console.WriteLine($"Secret   : {secret.Length} characters, from {secretSource}");

        // ---- connect and listen ----------------------------------------------------------
        using var stop = new ManualResetEventSlim(false);
        Console.CancelKeyPress += (_, e) =>
        {
            if (!_connected) return;   // still connecting: let Ctrl+C end the program
            e.Cancel = true; stop.Set();
        };

        try
        {
            Console.WriteLine("Connecting to the EIF broker... (Ctrl+C to abort)");
            IConnectionFactory factory = new ConnectionFactory(jmsUrl);
            using IConnection connection = factory.CreateConnection(agentId, secret);
            connection.ClientId = consumerName;
            connection.ExceptionListener += ex => Console.Error.WriteLine($"[connection error] {ex.Message}");
            connection.Start();
            _connected = true;

            using ISession session = connection.CreateSession();
            using IMessageConsumer consumer = session.CreateDurableConsumer(
                new ActiveMQTopic(topicName), consumerName, null, false);
            consumer.Listener += OnMessage;

            Console.WriteLine();
            Console.WriteLine("Connected. Now revise a Manufacturing Item in the sandbox. Press Ctrl+C to stop.");
            stop.Wait();
            Console.WriteLine($"Stopping. {_count} event(s) captured.");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Could not connect or subscribe: {ex.GetType().Name}: {ex.Message}");
            if (ex.InnerException != null) Console.Error.WriteLine($"  inner: {ex.InnerException.Message}");
            Console.Error.WriteLine("Check JmsUrl, AgentId, the agent secret, and that the agent may consume events.");
            return 2;
        }

        return 0;
    }

    private static string Get(JsonObject cfg, string key) => cfg[key]?.GetValue<string>() ?? "";

    private static void OnMessage(IMessage message)
    {
        int n = Interlocked.Increment(ref _count);
        try
        {
            string? bodyText = message switch
            {
                ITextMessage t => t.Text,
                IBytesMessage b => Encoding.UTF8.GetString(b.Content),
                _ => null
            };

            var envelope = new JsonObject
            {
                ["receivedAt"] = DateTime.UtcNow.ToString("o"),
                ["messageType"] = message.GetType().Name,
                ["jmsMessageId"] = message.NMSMessageId,
                ["jmsType"] = message.NMSType,
                ["jmsTimestamp"] = message.NMSTimestamp.ToUniversalTime().ToString("o"),
                ["destination"] = message.NMSDestination?.ToString(),
                ["properties"] = ToJson(message.Properties),
            };

            if (message is IMapMessage map)
                envelope["body"] = ToJson(map.Body);
            else if (bodyText != null)
                envelope["body"] = TryParse(bodyText) ?? JsonValue.Create(bodyText);

            string file = Path.Combine(_outputDir, $"{DateTime.Now:yyyyMMdd-HHmmss-fff}_{n:D4}.json");
            File.WriteAllText(file, envelope.ToJsonString(Pretty));

            string preview = (bodyText ?? "").Replace('\n', ' ');
            if (preview.Length > 160) preview = preview[..160] + "...";
            Console.WriteLine($"[{n}] {DateTime.Now:HH:mm:ss} saved {Path.GetFileName(file)}  {preview}");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[{n}] failed to save message: {ex.Message}");
        }
    }

    private static JsonNode? TryParse(string text)
    {
        try { return JsonNode.Parse(text); } catch { return null; }
    }

    private static JsonObject ToJson(IPrimitiveMap map)
    {
        var obj = new JsonObject();
        foreach (var key in map.Keys)
        {
            string k = key?.ToString() ?? "";
            object? v = map[k];
            obj[k] = v switch
            {
                null => null,
                string s => JsonValue.Create(s),
                bool b => JsonValue.Create(b),
                int i => JsonValue.Create(i),
                long l => JsonValue.Create(l),
                double d => JsonValue.Create(d),
                _ => JsonValue.Create(v.ToString())
            };
        }
        return obj;
    }
}
