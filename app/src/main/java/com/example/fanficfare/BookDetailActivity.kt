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
        path.text = bookPath
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
                        cover.visibility = View.GONE
                    }
                } else {
                    cover.visibility = View.GONE
                }
            } catch (e: Exception) {
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
            Toast.makeText(this, "Bridge not available", Toast.LENGTH_LONG).show()
            return
        }
        Thread {
            val resultJson = bridge.updateEpubFromPath(bookPath, filesDir.absolutePath)
            val result = org.json.JSONObject(resultJson)
            runOnUiThread {
                if (result.optBoolean("ok")) {
                    if (result.optBoolean("skipped")) {
                        showError("Update skipped: ${result.optString("reason", "already current")}")
                        return@runOnUiThread
                    }
                    val title = result.optString("title", bookTitle)
                    val author = result.optString("author", bookAuthor)
                    val path = result.optString("path", "")
                    val outputDir = SettingsActivity.getOutputDir(this)
                    try {
                        val source = File(path)
                        if (source.exists() && source.isFile) {
                            val finalPath = copyToOutputDir(source, outputDir)
                            finishWithResult(title, author, finalPath, System.currentTimeMillis())
                        } else {
                            finishWithResult(title, author, bookPath, System.currentTimeMillis())
                        }
                    } catch (e: Exception) {
                        showError("Update failed: ${e.message ?: "copy/output error"}")
                    }
                } else {
                    showError("Update failed: ${result.optString("error") ?: "unknown"}")
                }
            }
        }.start()
    }

    private fun forceDownloadBook() {
        val bridge = PythonBridge(applicationContext).takeIf { it.getInitError() == null } ?: run {
            Toast.makeText(this, "Bridge not available", Toast.LENGTH_LONG).show()
            return
        }
        Thread {
            val resultJson = bridge.forceDownloadFromEpub(bookPath, filesDir.absolutePath)
            val result = org.json.JSONObject(resultJson)
            runOnUiThread {
                if (result.optBoolean("ok")) {
                    val title = result.optString("title", bookTitle)
                    val author = result.optString("author", bookAuthor)
                    val path = result.optString("path", "")
                    val outputDir = SettingsActivity.getOutputDir(this)
                    try {
                        val source = File(path)
                        if (source.exists() && source.isFile) {
                            val finalPath = copyToOutputDir(source, outputDir)
                            finishWithResult(title, author, finalPath, System.currentTimeMillis())
                        } else {
                            finishWithResult(title, author, bookPath, System.currentTimeMillis())
                        }
                    } catch (e: Exception) {
                        showError("Download failed: ${e.message ?: "copy/output error"}")
                    }
                } else {
                    showError("Download failed: ${result.optString("error") ?: "unknown"}")
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
        val bridge = PythonBridge(applicationContext).takeIf { it.getInitError() == null } ?: run {
            Toast.makeText(this, "Bridge not available", Toast.LENGTH_LONG).show()
            return
        }
        Thread {
            val resultJson = bridge.deleteEpub(bookPath)
            val result = org.json.JSONObject(resultJson)
            runOnUiThread {
                if (result.optBoolean("ok")) {
                    setResult(RESULT_OK, Intent().putExtra("deleted", true))
                    finish()
                } else {
                    showError("Delete failed: ${result.optString("error") ?: "unknown"}")
                }
            }
        }.start()
    }

    private fun finishWithResult(title: String, author: String, path: String, modified: Long) {
        val data = Intent().apply {
            putExtra("title", title)
            putExtra("author", author)
            putExtra("path", path)
            putExtra("modified", modified)
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
