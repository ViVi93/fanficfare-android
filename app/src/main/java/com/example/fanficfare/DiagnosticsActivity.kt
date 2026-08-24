package com.example.fanficfare

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.chaquo.python.Python
import org.json.JSONObject

class DiagnosticsActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var importText: TextView
    private lateinit var logText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_diagnostics)

        statusText = findViewById(R.id.textDiagnosticStatus)
        importText = findViewById(R.id.textImportDiagnostics)
        logText = findViewById(R.id.textDiagnosticLog)

        updateStatus()
        showLog()

        findViewById<android.widget.Button>(R.id.buttonRefreshLog).setOnClickListener {
            showLog()
            updateStatus()
        }
        findViewById<android.widget.Button>(R.id.buttonClearLog).setOnClickListener {
            DiagnosticLog.clear(this)
            logText.text = "Log cleared"
            importText.text = ""
            importText.visibility = android.view.View.GONE
            updateStatus()
        }
        findViewById<android.widget.Button>(R.id.buttonShareLog).setOnClickListener {
            val file = DiagnosticLog.getFile(this)
            if (!file.exists()) {
                android.widget.Toast.makeText(this, "No log yet", android.widget.Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val uri: Uri = FileProvider.getUriForFile(this, "${packageName}.provider", file)
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(intent, "Share diagnostic log"))
        }
        findViewById<android.widget.Button>(R.id.buttonRunImportDiagnostics).setOnClickListener {
            runImportDiagnostics()
        }
    }

    private fun updateStatus() {
        val python = if (Python.isStarted()) Python.getInstance() else null
        val module = try { python?.getModule("fanficfare_bridge") } catch (e: Exception) { null }
        statusText.text = "Python: ${if (python != null) "started" else "missing"}\n" +
            "Module: ${if (module != null) "loaded" else "missing"}\n" +
            "Log file: ${DiagnosticLog.getFile(this).absolutePath}"
    }

    private fun showLog() {
        logText.text = DiagnosticLog.getText(this).ifBlank { "No log entries" }
    }

    private fun runImportDiagnostics() {
        val python = if (Python.isStarted()) Python.getInstance() else null
        val bridge = if (python != null) PythonBridge(applicationContext) else null
        if (bridge == null || bridge.getInitError() != null) {
            val err = bridge?.getInitError() ?: "null_bridge"
            importText.text = "Diagnostics unavailable: bridge not available\nInit error: ${err}"
            importText.visibility = android.view.View.VISIBLE
            return
        }
        importText.text = "Running import diagnostics..."
        importText.visibility = android.view.View.VISIBLE
        Thread {
            val resultJson = try {
                bridge.diagnoseFanFicFareImports()
            } catch (e: Exception) {
                DiagnosticLog.appendException(this, "Diagnostics.Import", "diagnostic_exception", e)
                "{\"ok\":false,\"error\":\"${e.javaClass.simpleName}: ${e.message ?: ""}\"}"
            }
            runOnUiThread {
                val sb = StringBuilder()
                sb.append("FanFicFare import diagnostics:\n")
                try {
                    val result = JSONObject(resultJson)
                    val arr = result.optJSONArray("results")
                    if (arr != null) {
                        for (i in 0 until arr.length()) {
                            val r = arr.getJSONObject(i)
                            val test = r.optString("test")
                            sb.append(if (r.optBoolean("ok")) "[OK] " else "[FAIL] ")
                            sb.append(test)
                            if (!r.optBoolean("ok")) {
                                sb.append("\n  ")
                                sb.append(r.optString("error_type", "Error"))
                                sb.append(": ")
                                sb.append(r.optString("error", ""))
                                val tb = r.optString("traceback")
                                if (!tb.isNullOrBlank()) {
                                    sb.append("\n")
                                    sb.append(tb)
                                }
                            }
                            sb.append("\n")
                        }
                    }
                } catch (e: Exception) {
                    sb.append("\nFailed to parse diagnostic result: ")
                    sb.append(e.javaClass.simpleName)
                    sb.append(": ")
                    sb.append(e.message ?: "")
                }
                val text = sb.toString().trim()
                importText.text = text
                importText.visibility = android.view.View.VISIBLE
                DiagnosticLog.append(this, "Diagnostics.Import", text.replace("\n", " "))
            }
        }.start()
    }
}
