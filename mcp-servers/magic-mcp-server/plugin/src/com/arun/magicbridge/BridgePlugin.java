package com.arun.magicbridge;

import com.nomagic.magicdraw.plugins.Plugin;

/**
 * Catia Magic plugin entry point. Starts a localhost-only HTTP bridge when
 * the application starts and stops it on exit. The Python MCP server
 * (magic-mcp-server/server.py) talks to this bridge.
 */
public class BridgePlugin extends Plugin {

    private BridgeServer server;

    @Override
    public void init() {
        try {
            server = new BridgeServer();
            server.start();
        } catch (Exception e) {
            System.err.println("[MagicMCPBridge] Failed to start bridge: " + e);
            e.printStackTrace();
        }
    }

    @Override
    public boolean close() {
        if (server != null) {
            server.stop();
        }
        return true;
    }

    @Override
    public boolean isSupported() {
        return true;
    }
}
