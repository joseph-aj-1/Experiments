package com.arun.magicbridge;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import javax.swing.SwingUtilities;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Localhost-only JSON-over-HTTP bridge into the open Catia Magic project.
 *
 * Security:
 *  - binds to 127.0.0.1 only;
 *  - every /api call needs the X-Bridge-Token header, a random secret
 *    regenerated at each start and written to ~/.magic-mcp/bridge.json
 *    (readable by your user account only);
 *  - requests carrying a browser Origin header are rejected, so web pages
 *    cannot drive the model.
 *
 * All model access runs on the Swing event thread, as the Catia Magic
 * OpenAPI requires. Edits run inside a SessionManager session, so each
 * MCP edit is one undoable command named "MCP: ...".
 */
public class BridgeServer {

    static final String VERSION = "1.0.0";
    private static final int DEFAULT_PORT = 8765;
    private static final int MAX_BODY = 8 * 1024 * 1024;

    private HttpServer http;
    private final String token;
    private final int port;
    private final ModelOps ops = new ModelOps();

    public BridgeServer() {
        this.port = resolvePort();
        byte[] b = new byte[32];
        new SecureRandom().nextBytes(b);
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        this.token = sb.toString();
    }

    private static int resolvePort() {
        String p = System.getProperty("magicbridge.port");
        if (p == null || p.isEmpty()) p = System.getenv("MAGIC_BRIDGE_PORT");
        try {
            return (p == null || p.isEmpty()) ? DEFAULT_PORT : Integer.parseInt(p.trim());
        } catch (NumberFormatException e) {
            return DEFAULT_PORT;
        }
    }

    public void start() throws Exception {
        http = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), port), 0);
        http.createContext("/health", this::handleHealth);
        http.createContext("/api/", this::handleApi);
        http.setExecutor(Executors.newFixedThreadPool(2));
        http.start();
        writeTokenFile();
        System.out.println("[MagicMCPBridge] Listening on http://127.0.0.1:" + port);
    }

    public void stop() {
        if (http != null) http.stop(0);
        File f = tokenFile();
        if (f.exists()) f.delete();
    }

    static File tokenFile() {
        return new File(new File(System.getProperty("user.home"), ".magic-mcp"), "bridge.json");
    }

    private void writeTokenFile() throws Exception {
        File f = tokenFile();
        f.getParentFile().mkdirs();
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("port", port);
        m.put("token", token);
        m.put("version", VERSION);
        try (OutputStream os = new FileOutputStream(f)) {
            os.write(Json.write(m).getBytes(StandardCharsets.UTF_8));
        }
        // Owner-only permissions where the platform supports it.
        f.setReadable(false, false);
        f.setReadable(true, true);
        f.setWritable(false, false);
        f.setWritable(true, true);
    }

    // ------------------------------------------------------------------

    private void handleHealth(HttpExchange ex) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("ok", true);
        m.put("bridge", "magic-mcp-bridge");
        m.put("version", VERSION);
        send(ex, 200, m);
    }

    private void handleApi(HttpExchange ex) {
        try {
            if (ex.getRequestHeaders().getFirst("Origin") != null) {
                send(ex, 403, error("Browser requests are not allowed"));
                return;
            }
            if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
                send(ex, 405, error("Use POST"));
                return;
            }
            String given = ex.getRequestHeaders().getFirst("X-Bridge-Token");
            if (given == null || !MessageDigest.isEqual(
                    given.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8))) {
                send(ex, 401, error("Missing or wrong X-Bridge-Token"));
                return;
            }
            final String action = ex.getRequestURI().getPath().substring("/api/".length());
            final Map<String, Object> body = Json.parseObject(readBody(ex.getRequestBody()));

            Object result = onEdt(new Callable<Object>() {
                public Object call() throws Exception {
                    return ops.dispatch(action, body);
                }
            });
            Map<String, Object> ok = new LinkedHashMap<String, Object>();
            ok.put("ok", true);
            ok.put("result", result);
            send(ex, 200, ok);
        } catch (BridgeException be) {
            send(ex, be.status, error(be.getMessage()));
        } catch (Throwable t) {
            t.printStackTrace();
            send(ex, 500, error(t.getClass().getSimpleName() + ": " + t.getMessage()));
        }
    }

    private static Object onEdt(final Callable<Object> c) throws Exception {
        if (SwingUtilities.isEventDispatchThread()) return c.call();
        final AtomicReference<Object> out = new AtomicReference<Object>();
        final AtomicReference<Throwable> err = new AtomicReference<Throwable>();
        try {
            SwingUtilities.invokeAndWait(new Runnable() {
                public void run() {
                    try {
                        out.set(c.call());
                    } catch (Throwable t) {
                        err.set(t);
                    }
                }
            });
        } catch (InvocationTargetException ite) {
            err.compareAndSet(null, ite.getCause());
        }
        Throwable t = err.get();
        if (t instanceof Exception) throw (Exception) t;
        if (t instanceof Error) throw (Error) t;
        return out.get();
    }

    private static String readBody(InputStream in) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            bos.write(buf, 0, n);
            if (bos.size() > MAX_BODY) throw new BridgeException(413, "Request too large");
        }
        return new String(bos.toByteArray(), StandardCharsets.UTF_8);
    }

    private static Map<String, Object> error(String msg) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("ok", false);
        m.put("error", msg);
        return m;
    }

    private static void send(HttpExchange ex, int status, Object payload) {
        try {
            byte[] bytes = Json.write(payload).getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            ex.sendResponseHeaders(status, bytes.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(bytes);
            }
        } catch (Exception ignored) {
            // client went away
        } finally {
            ex.close();
        }
    }
}
