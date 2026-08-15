package com.example.fanficfare

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.documentfile.provider.DocumentFile

class SettingsActivity : AppCompatActivity() {
    private val REQUEST_OUTPUT_DIR = 1001

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        val output = findViewById<EditText>(R.id.inputOutputDir)
        val prefs = getSharedPreferences("fanficfare_prefs", MODE_PRIVATE)
        output.setText(prefs.getString("output_dir", ""))

        findViewById<Button>(R.id.buttonPickFolder).setOnClickListener {
            val intent = Intent("android.provider.action.OPEN_DOCUMENT_TREE")
            startActivityForResult(intent, REQUEST_OUTPUT_DIR)
        }

        findViewById<Button>(R.id.buttonSave).setOnClickListener {
            val dir = output.text.toString().trim()
            prefs.edit().putString("output_dir", dir).apply()
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
            finish()
        }

        val btnAllFiles = findViewById<Button>(R.id.buttonAllFilesAccess)
        if (btnAllFiles != null) {
            btnAllFiles.setOnClickListener {
                try {
                    val intent = Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                    intent.data = android.net.Uri.parse("package:$packageName")
                    startActivity(intent)
                } catch (e: Exception) {
                    try {
                        startActivity(Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                    } catch (e2: Exception) {
                        Toast.makeText(this, "Cannot open settings: ${e2.message}", Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_OUTPUT_DIR && resultCode == RESULT_OK) {
            data?.data?.let { uri ->
                contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                findViewById<EditText>(R.id.inputOutputDir).setText(uri.toString())
            }
        }
    }

    companion object {
        fun getOutputDir(context: Context): String {
            val prefs = context.getSharedPreferences("fanficfare_prefs", Context.MODE_PRIVATE)
            return prefs.getString("output_dir", context.getExternalFilesDir(null)?.absolutePath ?: context.filesDir.absolutePath) ?: context.filesDir.absolutePath
        }

        fun getOutputDocumentFile(context: Context): DocumentFile? {
            val prefs = context.getSharedPreferences("fanficfare_prefs", Context.MODE_PRIVATE)
            val uriString = prefs.getString("output_dir", null)
            if (uriString.isNullOrBlank()) return null
            return DocumentFile.fromTreeUri(context, android.net.Uri.parse(uriString))
        }
    }
}
