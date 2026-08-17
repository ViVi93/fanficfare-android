package com.example.fanficfare

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.chaquo.python.Python

class DiagnosticsActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var logText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_diagnostics)

        statusText = findViewById(R.id.textDiagnosticStatus)
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
}
