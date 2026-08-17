package com.example.fanficfare

import android.content.ClipData
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.text.format.DateFormat
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File

class BookDetailActivity : AppCompatActivity() {

    private lateinit var bookTitle: String
    private lateinit var bookAuthor: String
    private lateinit var bookPath: String
    private var bookSource: String? = null
    private var bookModified: Long = 0
    private var bookSize: Long = 0
    private var bookChapters: Int = 0
    private var bookCover: String? = null
    private lateinit var bookUrl: String

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_book_detail)

        bookTitle = intent.getStringExtra("title") ?: ""
        bookAuthor = intent.getStringExtra("author") ?: ""
        bookPath = intent.getStringExtra("path") ?: ""
        bookSource = intent.getStringExtra("source")
        bookModified = intent.getLongExtra("modified", 0L)
        bookSize = intent.getLongExtra("size", 0L)
        bookChapters = intent.getIntExtra("chapters", 0)
        bookCover = intent.getStringExtra("cover")
        bookUrl = intent.getStringExtra("url") ?: ""

        val cover = findViewById<ImageView>(R.id.imageCover)
        val title = findViewById<TextView>(R.id.textTitle)
        val author = findViewById<TextView>(R.id.textAuthor)
        val chapters = findViewById<TextView>(R.id.textChapters)
        val url = findViewById<TextView>(R.id.textUrl)
        val path = findViewById<TextView>(R.id.textPath)
        val size = findViewById<TextView>(R.id.textSize)
        val modified = findViewById<TextView>(R.id.textModified)

        title.text = bookTitle.ifBlank { "Untitled" }
        author.text = bookAuthor.ifBlank { "Unknown author" }
        chapters.text = if (bookChapters > 0) "$bookChapters chapters" else ""
        url.text = bookUrl.ifBlank { "" }
        val displayPath = if (!bookSource.isNullOrBlank() && bookSource != bookPath) bookSource else bookPath
        path.text = displayPath
        size.text = formatSize(bookSize)
        modified.text = if (bookModified > 0) {
            DateFormat.format("yyyy-MM-dd HH:mm", bookModified).toString()
        } else {
            val file = File(bookPath)
            if (file.exists()) DateFormat.format("yyyy-MM-dd HH:mm", file.lastModified()).toString() else "Unknown date"
        }

        val coverData = bookCover
        if (!coverData.isNullOrBlank() && coverData.startsWith("data:")) {
            try {
                val comma = coverData.indexOf(",")
                if (comma > 0) {
                    val base64 = coverData.substring(comma + 1)
                    val bytes = android.util.Base64.decode(base64, android.util.Base64.DEFAULT)
                    val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bitmap != null) {
                        cover.setImageBitmap(bitmap)
                        cover.visibility = View.VISIBLE
                    } else {
                        // TEMP DIAGNOSTIC: BitmapFactory returned null
                        cover.visibility = View.GONE
                    }
                } else {
                    cover.visibility = View.GONE
                }
            } catch (e: Exception) {
                android.util.Log.d("FFF-Cover", "decodeByteArray failed: type=" + e.javaClass.simpleName + " msg=" + (e.message ?: ""))
                cover.visibility = View.GONE
            }
        } else {
            cover.visibility = View.GONE
        }

        val buttonUrl = findViewById<Button>(R.id.buttonUrl)
        if (bookUrl.isBlank()) {
            buttonUrl.visibility = View.GONE
        } else {
            buttonUrl.visibility = View.VISIBLE
            buttonUrl.setOnClickListener {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(bookUrl)))
            }
        }

        findViewById<Button>(R.id.buttonOpen).setOnClickListener { openBook() }
        findViewById<Button>(R.id.buttonUpdate).setOnClickListener { updateBook() }
        findViewById<Button>(R.id.buttonForce).setOnClickListener { forceDownloadBook() }
        findViewById<Button>(R.id.buttonShare).setOnClickListener { shareBook() }
        findViewById<Button>(R.id.buttonDelete).setOnClickListener { deleteBook() }
    }

    private fun openBook() {
        val file = File(bookPath)
        val uri = when {
            file.exists() && file.isFile -> FileProvider.getUriForFile(this, "${packageName}.provider", file)
            else -> Uri.parse(bookPath)
        }
        val mime = if (bookPath.startsWith("content://")) contentResolver.getType(uri) ?: "application/epub+zip" else "application/epub+zip"
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mime)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(this, "No EPUB reader installed", Toast.LENGTH_LONG).show()
        }
    }

    private fun updateBook() {
        val bridge = PythonBridge(applicationContext).takeIf { it.getInitError() == null } ?: run {
            DiagnosticLog.append(this, "Detail.Update", "bridge_unavailable")
            Toast.makeText(this, "Bridge not available", Toast.LENGTH_LONG).show()
            return
        }
        DiagnosticLog.append(this, "Detail.Update", "button_pressed title=$bookTitle url=$bookUrl path=$bookPath source=$bookSource")
        val url = bookUrl
        if (url.isBlank()) {
            DiagnosticLog.append(this, "Detail.Update", "validation_failed reason=blank_url")
            showError("No URL found for this book")
            return
        }
        DiagnosticLog.append(this, "Detail.Update", "validation_passed url=$url")
        setStatus("Updating...")
        DiagnosticLog.append(this, "Detail.Update", "starting")
        Thread {
            val resultJson = try {
                DiagnosticLog.append(this, "Detail.Update", "bridge_start")
                val raw = StorageBridge.withLocalEpub(this, bookPath) { localPath ->
                    DiagnosticLog.append(this, "Detail.Update", "bridge_input=${localPath.absolutePath}")
                    bridge.updateEpubFromPath(localPath.absolutePath, filesDir.absolutePath)
                }
                DiagnosticLog.append(this, "Detail.Update", "bridge_returned=${raw != null}")
                raw
            } catch (e: Exception) {
                DiagnosticLog.appendException(this, "Detail.Update", "storage_bridge_exception", e)
                runOnUiThread { showError("Cannot read EPUB from this location: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                DiagnosticLog.append(this, "Detail.Update", "bridge_null")
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    DiagnosticLog.append(this, "Detail.Update", "parsed ok=${result.optBoolean("ok")} skipped=${result.optBoolean("skipped")}")
                    if (result.optBoolean("ok")) {
                        if (result.optBoolean("skipped")) {
                            DiagnosticLog.append(this, "Detail.Update", "result=SKIPPED reason=${result.optString("reason", "already current")}")
                            showError("Update skipped: ${result.optString("reason", "already current")}")
                            return@runOnUiThread
                        }
                        val title = result.optString("title", bookTitle)
                        val author = result.optString("author", bookAuthor)
                        val internalPath = result.optString("path", "")
                        if (internalPath.isBlank()) {
                            DiagnosticLog.append(this, "Detail.Update", "result=FAILED empty_output_path")
                            showError("Update failed: bridge returned empty output path")
                            return@runOnUiThread
                        }
                        val outputDir = SettingsActivity.getOutputDir(this)
                        try {
                            val source = File(internalPath)
                            if (!source.exists() || !source.isFile) {
                                DiagnosticLog.append(this, "Detail.Update", "result=FAILED generated_file_missing=$internalPath")
                                showError("Update failed: generated file missing at $internalPath")
                                return@runOnUiThread
                            }
                            val finalPath = copyToOutputDir(source, outputDir)
                            DiagnosticLog.append(this, "Detail.Update", "copied finalPath=$finalPath")
                            Toast.makeText(applicationContext, "Updated: $title", Toast.LENGTH_LONG).show()
                            if (!isFinishing && !isDestroyed) {
                                window?.decorView?.postDelayed({
                                    if (!isFinishing && !isDestroyed) finishWithResult(title, author, finalPath, System.currentTimeMillis(), null)
                                }, 150)
                            }
                            DiagnosticLog.append(this, "Detail.Update", "result=SUCCESS title=$title path=$finalPath lifecycle_finishing=$isFinishing destroyed=$isDestroyed")
                        } catch (e: Exception) {
                            DiagnosticLog.appendException(this, "Detail.Update", "copy_output_exception", e)
                            showError("Update failed: ${e.message ?: "copy/output error"}")
                        }
                    } else {
                        DiagnosticLog.append(this, "Detail.Update", "result=FAILED error=${result.optString("error") ?: "unknown"}")
                        showError("Update failed: ${result.optString("error") ?: "unknown"}")
                    }
                } catch (e: Exception) {
                    DiagnosticLog.appendException(this, "Detail.Update", "result_parse_exception", e)
                    showError("Update failed: invalid response from bridge")
                }
            }
        }.start()
    }

    private fun forceDownloadBook() {
        val bridge = PythonBridge(applicationContext).takeIf { it.getInitError() == null } ?: run {
            DiagnosticLog.append(this, "Detail.ForceDownload", "bridge_unavailable")
            Toast.makeText(this, "Bridge not available", Toast.LENGTH_LONG).show()
            return
        }
        DiagnosticLog.append(this, "Detail.ForceDownload", "button_pressed title=$bookTitle url=$bookUrl path=$bookPath source=$bookSource")
        val url = bookUrl
        if (url.isBlank()) {
            DiagnosticLog.append(this, "Detail.ForceDownload", "validation_failed reason=blank_url")
            showError("No URL found for this book")
            return
        }
        DiagnosticLog.append(this, "Detail.ForceDownload", "validation_passed url=$url")
        setStatus("Force downloading...")
        DiagnosticLog.append(this, "Detail.ForceDownload", "starting")
        Thread {
            val resultJson = try {
                DiagnosticLog.append(this, "Detail.ForceDownload", "bridge_start")
                val raw = StorageBridge.withLocalEpub(this, bookPath) { localPath ->
                    DiagnosticLog.append(this, "Detail.ForceDownload", "bridge_input=${localPath.absolutePath}")
                    bridge.forceDownloadFromEpub(localPath.absolutePath, filesDir.absolutePath)
                }
                DiagnosticLog.append(this, "Detail.ForceDownload", "bridge_returned=${raw != null}")
                raw
            } catch (e: Exception) {
                DiagnosticLog.appendException(this, "Detail.ForceDownload", "storage_bridge_exception", e)
                runOnUiThread { showError("Cannot read EPUB from this location: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                DiagnosticLog.append(this, "Detail.ForceDownload", "bridge_null")
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    DiagnosticLog.append(this, "Detail.ForceDownload", "parsed ok=${result.optBoolean("ok")}")
                    if (result.optBoolean("ok")) {
                        val title = result.optString("title", bookTitle)
                        val author = result.optString("author", bookAuthor)
                        val internalPath = result.optString("path", "")
                        val outputDir = SettingsActivity.getOutputDir(this)
                        if (internalPath.isNotBlank()) {
                            try {
                                val source = File(internalPath)
                                if (source.exists() && source.isFile) {
                                    val finalPath = copyToOutputDir(source, outputDir)
                                    DiagnosticLog.append(this, "Detail.ForceDownload", "copied finalPath=$finalPath")
                                    Toast.makeText(applicationContext, "Force downloaded: $title", Toast.LENGTH_LONG).show()
                                    if (!isFinishing && !isDestroyed) {
                                        window?.decorView?.postDelayed({
                                            if (!isFinishing && !isDestroyed) finishWithResult(title, author, finalPath, System.currentTimeMillis(), null)
                                        }, 150)
                                    }
                                    DiagnosticLog.append(this, "Detail.ForceDownload", "result=SUCCESS title=$title path=$finalPath lifecycle_finishing=$isFinishing destroyed=$isDestroyed")
                                } else {
                                    DiagnosticLog.append(this, "Detail.ForceDownload", "result=SUCCESS missing_source_file=$internalPath")
                                    showError("Force downloaded: $title")
                                }
                            } catch (e: Exception) {
                                DiagnosticLog.appendException(this, "Detail.ForceDownload", "copy_output_exception", e)
                                showError("Force download failed: ${e.message ?: "copy/output error"}")
                            }
                        } else {
                            DiagnosticLog.append(this, "Detail.ForceDownload", "result=SUCCESS empty_internal_path")
                            showError("Force downloaded: $title")
                        }
                    } else {
                        val errorMsg = result.optString("error") ?: "unknown"
                        val detail = result.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        DiagnosticLog.append(this, "Detail.ForceDownload", "result=FAILED $fullMsg")
                        showError("Force download failed: $fullMsg")
                    }
                } catch (e: Exception) {
                    DiagnosticLog.appendException(this, "Detail.ForceDownload", "result_parse_exception", e)
                    showError("Force download failed: invalid response from bridge")
                }
            }
        }.start()
    }

    private fun shareBook() {
        val file = File(bookPath)
        val uri = when {
            file.exists() && file.isFile -> FileProvider.getUriForFile(this, "${packageName}.provider", file)
            else -> Uri.parse(bookPath)
        }
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/epub+zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            clipData = ClipData.newRawUri("epub", uri)
        }
        try {
            startActivity(Intent.createChooser(intent, "Share EPUB"))
        } catch (e: Exception) {
            Toast.makeText(this, "Cannot share this file", Toast.LENGTH_LONG).show()
        }
    }

    private fun deleteBook() {
        Thread {
            val ok = StorageBridge.deleteEpub(this, bookPath)
            runOnUiThread {
                if (ok) {
                    setResult(RESULT_OK, Intent().putExtra("deleted", true))
                    finish()
                } else {
                    showError("Delete failed")
                }
            }
        }.start()
    }

    private fun finishWithResult(title: String, author: String, path: String, modified: Long, source: String?) {
        val blocked = isFinishing || isDestroyed
        if (blocked) {
            DiagnosticLog.append(this, "Detail.Update", "finishWithResult blocked isFinishing=$isFinishing isDestroyed=$isDestroyed")
        }
        if (isFinishing || isDestroyed) return
        val data = Intent().apply {
            putExtra("title", title)
            putExtra("author", author)
            putExtra("path", path)
            putExtra("modified", modified)
            if (!source.isNullOrBlank()) putExtra("source", source)
        }
        setResult(RESULT_OK, data)
        finish()
    }

    private fun copyToOutputDir(sourceFile: File, outputDir: String): String {
        return if (outputDir.startsWith("content://")) {
            val treeUri = Uri.parse(outputDir)
            val treeDoc = androidx.documentfile.provider.DocumentFile.fromTreeUri(this, treeUri)
                ?: throw IllegalArgumentException("Invalid output directory")
            val newFile = treeDoc.createFile("application/epub+zip", sourceFile.name)
                ?: throw IllegalArgumentException("Cannot create file")
            contentResolver.openOutputStream(newFile.uri)?.use { out ->
                sourceFile.inputStream().use { it.copyTo(out) }
            } ?: throw IllegalArgumentException("Cannot open output stream")
            newFile.uri.toString()
        } else {
            val destDir = File(outputDir)
            if (!destDir.exists()) destDir.mkdirs()
            val outFile = File(destDir, sourceFile.name)
            sourceFile.copyTo(outFile, overwrite = true)
            outFile.absolutePath
        }
    }

    private fun setStatus(text: String) {
        runOnUiThread {
            findViewById<TextView>(R.id.textStatus).text = text
        }
    }

    private fun showError(message: String) {
        runOnUiThread {
            android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show()
        }
    }

    private fun formatSize(bytes: Long): String {
        if (bytes <= 0) return "0 KB"
        val kb = bytes / 1024.0
        return if (kb < 1024) String.format("%.1f KB", kb) else String.format("%.1f MB", kb / 1024.0)
    }
}
