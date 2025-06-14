#!/usr/bin/env node

/**
 * DesktopControllerMCP-MCP JSON-RPC Server mit Python Backend Integration
 * VERSION: 0.4.1-refactored
 */

const readline = require('readline');
const { spawn } = require('child_process');
const path = require('path');

// NEUE KLASSE: Kapselt die gesamte Python-Prozess-Logik
class PythonWorker {
  constructor() {
    this.pythonProcess = null;
    this.requestCallbacks = new Map(); // Speichert Callbacks für jede Anfrage-ID
    this.start();
  }

  start() {
    const scriptPath = path.join(__dirname, '..', 'mcp', 'mcp_stdio_worker.py'); // <-- NEUER DATEINAME HIER EINGETRAGEN
    console.error(`[PythonWorker] Starting worker: ${scriptPath}`);

    this.pythonProcess = spawn('poetry', ['run', 'python', scriptPath], {
      cwd: path.join(__dirname, '..'),
      stdio: ['pipe', 'pipe', 'pipe'] // stdin, stdout, stderr
    });
    
    // Listener für Antworten vom Python-Worker
    this.pythonProcess.stdout.on('data', (data) => {
      const lines = data.toString().split('\n').filter(line => line.trim() !== '');
      for (const line of lines) {
        try {
          const response = JSON.parse(line);
          const callback = this.requestCallbacks.get(response.id);
          if (callback) {
            callback(response);
            this.requestCallbacks.delete(response.id);
          } else {
            console.error(`[PythonWorker] Received response for unknown request ID: ${response.id}`);
          }
        } catch (e) {
            console.error(`[PythonWorker] Error parsing JSON from worker: ${line}`);
        }
      }
    });

    this.pythonProcess.stderr.on('data', (data) => {
      console.error(`[PythonWorker-STDERR] ${data.toString()}`);
    });

    this.pythonProcess.on('exit', (code) => {
      console.error(`[PythonWorker] Worker process exited with code ${code}`);
      // Hier könnte eine Neustart-Logik implementiert werden
    });
    
    this.pythonProcess.on('error', (err) => {
        console.error('[PythonWorker] Failed to start worker process.', err);
    });
  }

  // Methode zum Senden einer Anfrage an den Python-Worker
  sendRequest(request) {
    return new Promise((resolve, reject) => {
      this.requestCallbacks.set(request.id, (response) => {
        if (response.error) {
          reject(response.error);
        } else {
          resolve(response.result);
        }
      });
      
      try {
        this.pythonProcess.stdin.write(JSON.stringify(request) + '\n');
      } catch (e) {
        this.requestCallbacks.delete(request.id);
        reject(new Error("Failed to write to Python worker stdin. It may have crashed."));
      }
    });
  }

  cleanup() {
    if (this.pythonProcess) {
      console.error('[PythonWorker] Terminating worker process...');
      this.pythonProcess.kill('SIGINT');
    }
  }
}

// Haupt-Server-Klasse, jetzt viel schlanker
class DirectMCPServer {
  constructor() {
    this.pythonWorker = new PythonWorker(); // Instanziiert den Worker
    this.rl = null;
    this.requestIdCounter = 0;
    this.setupStdio();
    console.error('[DesktopControllerMCP-MCP-Direct] Server is running and waiting for messages.');
  }

  setupStdio() {
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: false
    });

    this.rl.on('line', (line) => {
      this.handleIncomingMessage(line);
    });
  }

  async handleIncomingMessage(line) {
    try {
      const message = JSON.parse(line.trim());
      console.error(`[DesktopControllerMCP-MCP-Direct] Received: ${message.method}`);
      const response = await this.processRequest(message);
      // Sende die Antwort zurück an Claude Desktop
      console.log(JSON.stringify(response));
    } catch (error) {
      console.error(`[DesktopControllerMCP-MCP-Direct] Error processing message: ${error.message}`);
      // Sende eine Fehlerantwort an Claude Desktop
      console.log(JSON.stringify({
        jsonrpc: '2.0',
        id: null,
        error: { code: -32603, message: 'Internal error', data: error.message }
      }));
    }
  }
  
  async processRequest(request) {
      const { method, params, id } = request;

      if (method === 'initialize') {
          return { jsonrpc: '2.0', id, result: { serverInfo: { name: 'DesktopControllerMCP-MCP' } } };
      }
      
      if (method === 'tools/list') {
        // Die Tool-Liste kann hier statisch definiert oder vom Python-Worker geholt werden
        const pythonRequest = { jsonrpc: '2.0', method: 'tools/list', id: `py_${this.requestIdCounter++}` };
        const toolsResult = await this.pythonWorker.sendRequest(pythonRequest);
        return { jsonrpc: '2.0', id, result: toolsResult };
      }

      if (method === 'tools/call') {
        const pythonRequest = { jsonrpc: '2.0', method: 'tools/call', params, id: `py_${this.requestIdCounter++}` };
        try {
          const toolResult = await this.pythonWorker.sendRequest(pythonRequest);
          return { jsonrpc: '2.0', id, result: toolResult };
        } catch (error) {
          return { jsonrpc: '2.0', id, error };
        }
      }

      return {
          jsonrpc: '2.0',
          id,
          error: { code: -32601, message: 'Method not found' }
      };
  }

  cleanup() {
      this.pythonWorker.cleanup();
  }
}

// Start des Servers
const server = new DirectMCPServer();

process.on('SIGINT', () => {
  console.error('[DesktopControllerMCP-MCP-Direct] Shutting down...');
  server.cleanup();
  process.exit(0);
});

process.on('SIGTERM', () => {
    console.error('[DesktopControllerMCP-MCP-Direct] Received SIGTERM, shutting down...');
    server.cleanup();
    process.exit(0);
});
