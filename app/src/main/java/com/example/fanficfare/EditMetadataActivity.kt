package com.example.fanficfare

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat

class EditMetadataActivity : AppCompatActivity() {

    private lateinit var bridge: PythonBridge
    private lateinit var epubPath: String
    private var backupSuffix: String? = ".metadata_edit_bak"

    // UI references
    private lateinit var editTitle: EditText
    private lateinit var editAuthor: EditText
    private lateinit var editLanguage: EditText
    private lateinit var editPublisher: EditText
    private lateinit var editDescription: EditText
    private lateinit var editTags: EditText
    private lateinit var editSeries: EditText
    private lateinit var editSeriesIndex: EditText
    private lateinit var editRating: EditText
    private lateinit var editIsbn: EditText
    private lateinit var editPubdate: EditText
    private lateinit var editRights: EditText
    private lateinit var buttonSave: Button
    private lateinit var buttonCancel: Button
    private lateinit var buttonExportOpf: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            WindowCompat.setDecorFitsSystemWindows(window, true)
        }
        setContentView(R.layout.activity_edit_metadata)
        Log.d("EditMetadata", "ENTER")

        epubPath = intent.getStringExtra("epub_path") ?: ""
        Log.d("EditMetadata", "epub_path=$epubPath")

        bridge = PythonBridge(applicationContext)
        if (bridge.getInitError() != null) {
            showError("Bridge not available: ${bridge.getInitError()}")
            finish()
            return
        }

        // Initialize UI references
        editTitle = findViewById(R.id.editTitle)
        editAuthor = findViewById(R.id.editAuthor)
        editLanguage = findViewById(R.id.editLanguage)
        editPublisher = findViewById(R.id.editPublisher)
        editDescription = findViewById(R.id.editDescription)
        editTags = findViewById(R.id.editTags)
        editSeries = findViewById(R.id.editSeries)
        editSeriesIndex = findViewById(R.id.editSeriesIndex)
        editRating = findViewById(R.id.editRating)
        editIsbn = findViewById(R.id.editIsbn)
        editPubdate = findViewById(R.id.editPubdate)
        editRights = findViewById(R.id.editRights)
        buttonSave = findViewById(R.id.buttonSave)
        buttonCancel = findViewById(R.id.buttonCancel)
        buttonExportOpf = findViewById(R.id.buttonExportOpf)

        // Populate fields from intent extras
        editTitle.setText(intent.getStringExtra("title") ?: "")
        val authors = intent.getStringArrayListExtra("authors") ?: arrayListOf("")
        editAuthor.setText(authors.joinToString(", "))
        editLanguage.setText(intent.getStringExtra("language") ?: "")
        editPublisher.setText(intent.getStringExtra("publisher") ?: "")
        editDescription.setText(intent.getStringExtra("description") ?: "")
        editTags.setText(intent.getStringExtra("tags") ?: "")
        editSeries.setText(intent.getStringExtra("series") ?: "")
        editSeriesIndex.setText(intent.getStringExtra("series_index") ?: "")
        editRating.setText(intent.getStringExtra("rating") ?: "")
        editIsbn.setText(intent.getStringExtra("isbn") ?: "")
        editPubdate.setText(intent.getStringExtra("pubdate") ?: "")
        editRights.setText(intent.getStringExtra("rights") ?: "")

        buttonSave.setOnClickListener { saveMetadata() }
        buttonCancel.setOnClickListener {
            setResult(RESULT_CANCELED)
            finish()
        }
        buttonExportOpf.setOnClickListener { exportOpf() }

        Log.d("EditMetadata", "UI ready")
    }

    private fun saveMetadata() {
        val bridge = this.bridge
        if (bridge.getInitError() != null) {
            showError("Bridge not available")
            return
        }

        val title = editTitle.text.toString().trim()
        val authorStr = editAuthor.text.toString().trim()
        val authors = authorStr.split(",").map { it.trim() }.filter { it.isNotBlank() }
        if (authors.isEmpty()) {
            showError("At least one author is required")
            return
        }

        val fields = org.json.JSONObject().apply {
            put("title", title)
            put("authors", org.json.JSONArray(authors))
            put("languages", org.json.JSONArray(listOf(editLanguage.text.toString().trim()).filter { it.isNotBlank() }))
            put("publisher", editPublisher.text.toString().trim())
            put("description", editDescription.text.toString().trim())
            put("tags", editTags.text.toString().trim())
            put("series", editSeries.text.toString().trim())
            put("series_index", editSeriesIndex.text.toString().trim())
            put("rating", editRating.text.toString().trim())
            put("isbn", editIsbn.text.toString().trim())
            put("pubdate", editPubdate.text.toString().trim())
            put("rights", editRights.text.toString().trim())
        }

        Log.d("EditMetadata", "save_metadata_start title=$title path=$epubPath")

        Thread {
            val resultJson = try {
                StorageBridge.withLocalEpub(this, epubPath) { localPath ->
                    bridge.writeEpubMetadata(
                        localPath.absolutePath,
                        fields.toString(),
                        outputPath = null,
                        backupSuffix = backupSuffix
                    )
                }
            } catch (e: Exception) {
                Log.e("EditMetadata", "save_metadata_exception", e)
                runOnUiThread { showError("Cannot read EPUB: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }

            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    if (result.optBoolean("ok")) {
                        val changedFields = result.optJSONArray("changed_fields")
                        val changedList = mutableListOf<String>()
                        if (changedFields != null) {
                            for (i in 0 until changedFields.length()) {
                                changedList.add(changedFields.getString(i))
                            }
                        }
                        Log.d("EditMetadata", "result=SUCCESS changed=$changedList")
                        Toast.makeText(this, "Metadata saved: ${changedList.joinToString(", ")}", Toast.LENGTH_LONG).show()
                        val modified = System.currentTimeMillis()
                        val intent = Intent().apply {
                            putExtra("title", title)
                            putStringArrayListExtra("authors", ArrayList(authors))
                            putExtra("output_path", epubPath)
                            putExtra("modified", modified)
                        }
                        setResult(RESULT_OK, intent)
                        finish()
                    } else {
                        Log.e("EditMetadata", "result=FAILED error=${result.optString("error")}")
                        showError("Save failed: ${result.optString("error")}")
                    }
                } catch (e: Exception) {
                    Log.e("EditMetadata", "result_parse_error", e)
                    showError("Save failed: invalid response from bridge")
                }
            }
        }.start()
    }

    private fun exportOpf() {
        val bridge = this.bridge
        if (bridge.getInitError() != null) {
            showError("Bridge not available")
            return
        }

        Thread {
            val resultJson = try {
                StorageBridge.withLocalEpub(this, epubPath) { localPath ->
                    bridge.exportEpubOpf(localPath.absolutePath)
                }
            } catch (e: Exception) {
                runOnUiThread { showError("Cannot read EPUB: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }

            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    if (result.optBoolean("ok")) {
                        val opfXml = result.optString("opf", "")
                        val dialog = AlertDialog.Builder(this)
                            .setTitle("OPF XML")
                            .setMessage(opfXml)
                            .setPositiveButton("Copy to clipboard") { _, _ ->
                                val clipboard = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
                                val clip = ClipData.newPlainText("OPF XML", opfXml)
                                clipboard.setPrimaryClip(clip)
                                Toast.makeText(this, "Copied to clipboard", Toast.LENGTH_SHORT).show()
                            }
                            .setNegativeButton("Close", null)
                            .show()
                        val message = dialog.findViewById<TextView>(android.R.id.message)
                        message?.post {
                            message.maxLines = 20
                            message.scrollBarStyle = View.SCROLLBARS_INSIDE_INSET
                            message.isVerticalScrollBarEnabled = true
                        }
                    } else {
                        showError("Export failed: ${result.optString("error")}")
                    }
                } catch (e: Exception) {
                    showError("Export failed: ${e.message ?: "unknown"}")
                }
            }
        }.start()
    }

    private fun showError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
