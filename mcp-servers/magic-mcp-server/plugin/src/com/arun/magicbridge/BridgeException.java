package com.arun.magicbridge;

/** An error that should reach the MCP client with a specific HTTP status. */
public class BridgeException extends Exception {
    final int status;

    public BridgeException(int status, String message) {
        super(message);
        this.status = status;
    }

    public BridgeException(String message) {
        this(400, message);
    }
}
