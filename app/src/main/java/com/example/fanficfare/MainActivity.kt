package com.example.fanficfare

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.documentfile.provider.DocumentFile
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.fanficfare.adapter.BookAdapter
import com.example.fanficfare.model.BookItem
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.File
import java.io.IOException

class MainActivity : AppCompatActivity() {

    private val downloads = mutableListOf<BookItem>()
    private lateinit var bookAdapter: BookAdapter
    private var pythonBridge: PythonBridge? = null
    private var selectedBook: BookItem? = null
    private var currentSort: String = "modified"
    private var libraryFolderPath: String? = null
    private val REQUEST_BOOK_DETAIL = 1003

    private fun hasStoragePermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED
                || ContextCompat.checkSelfPermission(this, android.Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        } else true
    }

    private fun requestStoragePermission(onGranted: () -> Unit) {
        val perms = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(android.Manifest.permission.READ_MEDIA_IMAGES)
        } else {
            perms.add(android.Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            perms.add(android.Manifest.permission.MANAGE_EXTERNAL_STORAGE)
        }
        ActivityCompat.requestPermissions(this, perms.toTypedArray(), 1001)
    }

    private fun ensureStoragePermission(action: () -> Unit) {
        if (hasStoragePermission()) {
            action()
        } else {
            requestStoragePermission {
                if (hasStoragePermission()) action() else toast("Storage permission denied")
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        if (!Python.isStarted()) {
            try {
                Python.start(com.chaquo.python.android.AndroidPlatform(this))
            } catch (e: Exception) {
                toast("Python init failed: ${e.message}")
            }
        }
        pythonBridge = PythonBridge(this)
        pythonBridge?.getInitError()?.let { error ->
            toast("Bridge init failed: $error")
        }
        pythonBridge?.getFanFicFareError()?.let { error ->
            toast("FanFicFare init failed: $error")
        }
        pythonBridge?.initialize(SettingsActivity.getConfigDir(this).absolutePath)

        bookAdapter = BookAdapter(downloads) { book ->
            selectedBook = book
            showBookOptionsDialog(book)
        }
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).layoutManager = LinearLayoutManager(this)
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter

        updateEmptyState()
        loadPersistedLibrary()

        val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
        toolbar.inflateMenu(R.menu.main_menu)
        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_download -> {
                    showDownloadDialog()
                    true
                }
                R.id.action_load_library -> {
                    showLoadLibraryDialog()
                    true
                }
                R.id.action_settings -> {
                    startActivity(android.content.Intent(this, SettingsActivity::class.java))
                    true
                }
                R.id.action_diagnostics -> {
                    startActivity(Intent(this, DiagnosticsActivity::class.java))
                    true
                }
                R.id.action_refresh_all -> {
                    refreshAllBooks()
                    true
                }
                R.id.action_sort -> {
                    showSortDialog()
                    true
                }
                R.id.action_search -> {
                    showSearchDialog()
                    true
                }
                else -> false
            }
        }
    }

    private fun toast(text: String) {
        android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show()
    }

    private fun showError(message: String) {
        toast(message)
    }

    private fun chooseCover(existing: String?, returned: String?): String {
        val newCover = returned?.trim().orEmpty()
        return if (newCover.isNotEmpty()) newCover else existing?.trim().orEmpty()
    }

    private fun getPythonBridge(): PythonBridge? = pythonBridge

    private fun findBookByIdentity(book: BookItem): Int {
        val byUrl = downloads.indexOfFirst { it.url.isNotBlank() && it.url == book.url }
        if (byUrl >= 0) return byUrl
        val normalized = book.uriString.trim()
        if (normalized.isNotBlank()) {
            return downloads.indexOfFirst { it.uriString.trim() == normalized }
        }
        return -1
    }

    private fun updateEmptyState() {
        val empty = findViewById<TextView>(R.id.textEmpty)
        empty?.visibility = if (downloads.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun showBookOptionsDialog(book: BookItem) {
        val options = mutableListOf<String>()
        if (book.url.isNotBlank()) {
            options.add("Update")
            options.add("Force Download")
        }
        options.add("Details")
        options.add("Delete")

        AlertDialog.Builder(this)
            .setTitle(book.title.ifBlank { "Book" })
            .setItems(options.toTypedArray()) { _, which ->
                val choice = options[which]
                when (choice) {
                    "Update" -> updateBook(book)
                    "Force Download" -> forceDownloadBook(book)
                    "Details" -> openBookDetail(book)
                    "Delete" -> deleteBook(book)
                }
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun openBookDetail(book: BookItem) {
        val intent = Intent(this, BookDetailActivity::class.java)
            .putExtra("title", book.title)
            .putExtra("author", book.author)
            .putExtra("path", book.uriString)
            .putExtra("modified", book.lastModified)
            .putExtra("size", book.sizeBytes)
            .putExtra("url", book.url)
            .putExtra("chapters", book.chapters)
        startActivityForResult(intent, REQUEST_BOOK_DETAIL)
    }

    private fun updateBook(book: BookItem) {
        DiagnosticLog.append(this, "Main.Update", "button_pressed title=${book.title} url=${book.url} path=${book.uriString}")
        val url = book.url
        if (url.isBlank()) {
            DiagnosticLog.append(this, "Main.Update", "validation_failed=blank_url")
            toast("No URL found for this book")
            return
        }
        toast("Updating...")
        DiagnosticLog.append(this, "Main.Update", "starting")
        Thread {
            val resultJson = try {
                DiagnosticLog.append(this, "Main.Update", "bridge_start")
                val raw = StorageBridge.withLocalEpub(this, book.uriString) { localPath ->
                    DiagnosticLog.append(this, "Main.Update", "bridge_input=${localPath.absolutePath}")
                    pythonBridge?.updateEpubFromPath(localPath.absolutePath, filesDir.absolutePath)
                }
                DiagnosticLog.append(this, "Main.Update", "bridge_returned=${raw != null}")
                raw
            } catch (e: Exception) {
                DiagnosticLog.appendException(this, "Main.Update", "storage_bridge_exception", e)
                runOnUiThread { showError("Cannot read EPUB from this location: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                DiagnosticLog.append(this, "Main.Update", "bridge_null")
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    DiagnosticLog.append(this, "Main.Update", "parsed ok=${result.optBoolean("ok")} skipped=${result.optBoolean("skipped")}")
                    if (result.optBoolean("ok")) {
                        if (result.optBoolean("skipped")) {
                            DiagnosticLog.append(this, "Main.Update", "result=SKIPPED reason=${result.optString("reason", "already current")}")
                            showError("Update skipped: ${result.optString("reason", "already current")}")
                            return@runOnUiThread
                        }
                        val title = result.optString("title", book.title)
                        val author = result.optString("author", book.author)
                        val internalPath = result.optString("path", "")
                        if (internalPath.isBlank()) {
                            DiagnosticLog.append(this, "Main.Update", "result=FAILED empty_output_path")
                            showError("Update failed: bridge returned empty output path")
                            return@runOnUiThread
                        }
                        val outputDir = SettingsActivity.getOutputDir(this@MainActivity)
                        try {
                            val source = File(internalPath)
                            if (!source.exists() || !source.isFile) {
                                DiagnosticLog.append(this, "Main.Update", "result=FAILED generated_file_missing=$internalPath")
                                showError("Update failed: generated file missing at $internalPath")
                                return@runOnUiThread
                            }
                            val finalPath = copyToOutputDir(source, outputDir)
                            val updated = BookItem(
                                title = title,
                                author = author,
                                uriString = finalPath,
                                lastModified = result.optLong("modified", System.currentTimeMillis()),
                                sizeBytes = result.optLong("size", 0L),
                                coverUriString = result.optString("cover", book.coverUriString ?: ""),
                                url = result.optString("url", book.url ?: ""),
                                chapters = result.optInt("chapters", 0)
                            )
                            val idx = findBookByIdentity(book)
                            DiagnosticLog.append(this, "Main.Update", "list_update idx=$idx finalPath=$finalPath")
                            if (idx >= 0) downloads[idx] = updated else downloads.add(0, updated)
                            bookAdapter.notifyDataSetChanged()
                            toast("Updated: $title")
                            persistLibrary()
                            DiagnosticLog.append(this, "Main.Update", "result=SUCCESS title=$title path=$finalPath")
                        } catch (e: Exception) {
                            DiagnosticLog.appendException(this, "Main.Update", "copy_output_exception", e)
                            showError("Update failed: ${e.message ?: "copy/output error"}")
                        }
                    } else {
                        DiagnosticLog.append(this, "Main.Update", "result=FAILED error=${result.optString("error") ?: "unknown"}")
                        showError("Update failed: ${result.optString("error") ?: "unknown"}")
                    }
                } catch (e: Exception) {
                    DiagnosticLog.appendException(this, "Main.Update", "result_parse_exception", e)
                    showError("Update failed: invalid response from bridge")
                }
            }
        }.start()
    }

    private fun forceDownloadBook(book: BookItem) {
        DiagnosticLog.append(this, "Main.ForceDownload", "button_pressed title=${book.title} url=${book.url} path=${book.uriString}")
        val url = book.url
        if (url.isBlank()) {
            DiagnosticLog.append(this, "Main.ForceDownload", "validation_failed=blank_url")
            toast("No URL found for this book")
            return
        }
        toast("Force downloading...")
        DiagnosticLog.append(this, "Main.ForceDownload", "starting")
        Thread {
            val resultJson = try {
                DiagnosticLog.append(this, "Main.ForceDownload", "bridge_start")
                val raw = StorageBridge.withLocalEpub(this, book.uriString) { localPath ->
                    DiagnosticLog.append(this, "Main.ForceDownload", "bridge_input=${localPath.absolutePath}")
                    pythonBridge?.forceDownloadFromEpub(localPath.absolutePath, filesDir.absolutePath)
                }
                DiagnosticLog.append(this, "Main.ForceDownload", "bridge_returned=${raw != null}")
                raw
            } catch (e: Exception) {
                DiagnosticLog.appendException(this, "Main.ForceDownload", "storage_bridge_exception", e)
                runOnUiThread { showError("Cannot read EPUB from this location: ${e.message ?: e.javaClass.simpleName}") }
                return@Thread
            } ?: run {
                DiagnosticLog.append(this, "Main.ForceDownload", "bridge_null")
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
                    DiagnosticLog.append(this, "Main.ForceDownload", "parsed ok=${result.optBoolean("ok")}")
                    if (result.optBoolean("ok")) {
                        val title = result.optString("title", book.title)
                        val author = result.optString("author", book.author)
                        val internalPath = result.optString("path", "")
                        val outputDir = SettingsActivity.getOutputDir(this@MainActivity)
                        if (internalPath.isNotBlank()) {
                            try {
                                val source = File(internalPath)
                                if (source.exists() && source.isFile) {
                                    val finalPath = copyToOutputDir(source, outputDir)
                                    val updated = BookItem(
                                        title = title,
                                        author = author,
                                        uriString = finalPath,
                                        lastModified = result.optLong("modified", System.currentTimeMillis()),
                                        sizeBytes = result.optLong("size", 0L),
                                        coverUriString = chooseCover(book.coverUriString, result.optString("cover")),
                                        url = result.optString("url", book.url ?: ""),
                                        chapters = result.optInt("chapters", 0)
                                    )
                                    val fileObj = result.optJSONObject("file")
                                    val fileLog = if (fileObj != null) {
                                        "exists_before=${fileObj.optBoolean("exists_before")} size_before=${fileObj.optString("size_before", "<null>")} mtime_before=${fileObj.optString("mtime_before", "<null>")} exists_after=${fileObj.optBoolean("exists_after")} size_after=${fileObj.optString("size_after", "<null>")} mtime_after=${fileObj.optString("mtime_after", "<null>")} changed=${fileObj.optBoolean("changed")}"
                                    } else {
                                        "file_state=missing"
                                    }
                                    val idx = findBookByIdentity(book)
                                    DiagnosticLog.append(this, "Main.ForceDownload", "list_update idx=$idx finalPath=$finalPath $fileLog")
                                    if (idx >= 0) downloads[idx] = updated else downloads.add(0, updated)
                                    bookAdapter.notifyDataSetChanged()
                                    toast("Downloaded: $title")
                                    toast("Downloaded: $title")
                                    persistLibrary()
                                    DiagnosticLog.append(this, "Main.ForceDownload", "result=SUCCESS title=$title path=$finalPath $fileLog")
                                } else {
                                    DiagnosticLog.append(this, "Main.ForceDownload", "result=SUCCESS missing_source_file=$internalPath")
                                    toast("Downloaded: $title")
                                    toast("Downloaded: $title")
                                    persistLibrary()
                                }
                            } catch (e: Exception) {
                                DiagnosticLog.appendException(this, "Main.ForceDownload", "copy_output_exception", e)
                                showError("Download failed: ${e.message ?: "copy/output error"}")
                            }
                        } else {
                            DiagnosticLog.append(this, "Main.ForceDownload", "result=SUCCESS empty_internal_path")
                            toast("Downloaded: $title")
                            toast("Downloaded: $title")
                            persistLibrary()
                        }
                    } else {
                        val errorMsg = result.optString("error") ?: "unknown"
                        val detail = result.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        DiagnosticLog.append(this, "Main.ForceDownload", "result=FAILED $fullMsg")
                        showError("Download failed: $fullMsg")
                    }
                } catch (e: Exception) {
                    DiagnosticLog.appendException(this, "Main.ForceDownload", "result_parse_exception", e)
                    showError("Force download failed: invalid response from bridge")
                }
            }
        }.start()
    }

    private fun deleteBook(book: BookItem) {
        AlertDialog.Builder(this)
            .setTitle("Delete")
            .setMessage("Delete ${book.title.ifBlank { "this book" }}?")
            .setPositiveButton("Delete") { _, _ ->
                Thread {
                    val ok = StorageBridge.deleteEpub(this, book.uriString)
                    runOnUiThread {
                        if (ok) {
                            downloads.remove(book)
                            bookAdapter.notifyDataSetChanged()
                            updateEmptyState()
                            toast("Deleted")
                            persistLibrary()
                        } else {
                            showError("Delete failed")
                        }
                    }
                }.start()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun refreshBookPath(oldBook: BookItem, title: String, author: String, path: String) {
        val index = findBookByIdentity(oldBook)
        if (index >= 0) {
            val updated = oldBook.copy(
                title = title,
                author = author,
                uriString = path,
                lastModified = System.currentTimeMillis()
            )
            downloads[index] = updated
            bookAdapter.notifyDataSetChanged()
        }
    }

    private fun showDownloadDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_download, null)
        val input = view.findViewById<EditText>(R.id.inputUrl)
        view.findViewById<android.widget.Button>(R.id.buttonDownload).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            toast("Downloading...")
            Thread {
                DiagnosticLog.append(this, "Main.Download", "START url=$url")
                val startMs = System.currentTimeMillis()
                val watchdog = android.os.Handler(mainLooper)
                val watchdogRunnable = object : Runnable {
                    override fun run() {
                        val elapsed = (System.currentTimeMillis() - startMs) / 1000
                        DiagnosticLog.append(this@MainActivity, "Main.Download", "RUNNING elapsed=${elapsed}s")
                        watchdog.postDelayed(this, 15000)
                    }
                }
                watchdog.postDelayed(watchdogRunnable, 15000)
                val resultJson = try {
                    DiagnosticLog.append(this, "Main.Download", "bridge_call method=fanficfareDownload url=$url outDir=${filesDir.absolutePath}")
                    val callStart = System.currentTimeMillis()
                    val raw = pythonBridge?.fanficfareDownload(url, filesDir.absolutePath)
                        ?: """{"ok":false,"error":"bridge missing"}"""
                    val elapsedCall = System.currentTimeMillis() - callStart
                    watchdog.removeCallbacksAndMessages(null)
                    DiagnosticLog.append(this, "Main.Download", "bridge_returned=${raw != null} elapsed=${elapsedCall}ms")
                    DiagnosticLog.append(this, "Main.Download", "Python.debug=${pythonBridge?.readDownloadDebug()?.replace("\n", " ") ?: "<null>"}")
                    raw
                } catch (e: Exception) {
                    watchdog.removeCallbacksAndMessages(null)
                    DiagnosticLog.appendException(this, "Main.Download", "bridge_exception", e)
                    """{"ok":false,"error":${JSONObject().put("msg", e.message).toString()}}"""
                }
                val result = json(resultJson)
                runOnUiThread {
                    if (result?.optBoolean("ok") == true) {
                        val title = result.optString("title", "story")
                        val internalPath = result.optString("path", "")
                        val outputDir = SettingsActivity.getOutputDir(this@MainActivity)
                        if (internalPath.isBlank()) {
                            showError("Download failed: missing output path")
                            return@runOnUiThread
                        }
                        try {
                            val source = File(internalPath)
                            if (!source.exists() || !source.isFile) {
                                showError("Download failed: generated file missing")
                                return@runOnUiThread
                            }
                            val finalPath = copyToOutputDir(source, outputDir)
                            toast("Downloaded: $title")
                            toast("Downloaded: $title")
                            val author = result.optString("author", "")
                            val url = result.optString("url", "")
                            val chapters = result.optInt("chapters", 0)
                            val cover = result.optString("cover", "")
                            val size = result.optLong("size", 0L)
                            val modified = result.optLong("modified", 0L)
                            val newBook = BookItem(title, author, finalPath, modified, size, cover, url, chapters, finalPath)
                            val existing = findBookByIdentity(newBook)
                            if (existing >= 0) {
                                downloads[existing] = newBook
                            } else {
                                downloads.add(0, newBook)
                            }
                            bookAdapter.notifyDataSetChanged()
                            updateEmptyState()
                            persistLibrary()
                            DiagnosticLog.append(this, "Main.Download", "result=SUCCESS")
                        } catch (e: Exception) {
                            DiagnosticLog.appendException(this, "Main.Download", "copy_output_exception", e)
                            showError("Download failed: ${e.message}")
                        }
                    } else {
                        val errorMsg = result?.optString("error") ?: "unknown"
                        val detail = result?.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        DiagnosticLog.append(this, "Main.Download", "result=FAILED $fullMsg")
                        showError("Download failed: $fullMsg")
                    }
                    DiagnosticLog.append(this, "Main.Download", "END")
                }
            }.start()
        }
        view.findViewById<android.widget.Button>(R.id.buttonUpdate).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            toast("Updating...")
            Thread {
                DiagnosticLog.append(this, "Main.Update", "START url=$url")
                val resultJson = try {
                    DiagnosticLog.append(this, "Main.Update", "bridge_start")
                    val raw = pythonBridge?.fanficfareMetadata(url)
                        ?: """{"ok":false,"error":"bridge missing"}"""
                    DiagnosticLog.append(this, "Main.Update", "bridge_returned=${raw != null}")
                    raw
                } catch (e: Exception) {
                    DiagnosticLog.appendException(this, "Main.Update", "bridge_exception", e)
                    """{"ok":false,"error":${JSONObject().put("msg", e.message).toString()}}"""
                }
                val result = json(resultJson)
                runOnUiThread {
                    if (result?.optBoolean("ok") == true) {
                        toast("Metadata fetched")
                        DiagnosticLog.append(this, "Main.Update", "result=SUCCESS")
                    } else {
                        val errorMsg = result?.optString("error") ?: "unknown"
                        val detail = result?.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        DiagnosticLog.append(this, "Main.Update", "result=FAILED $fullMsg")
                        showError("Update check failed: $fullMsg")
                    }
                    DiagnosticLog.append(this, "Main.Update", "END")
                }
            }.start()
        }
        AlertDialog.Builder(this)
            .setTitle("FanFicFare")
            .setView(view)
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showLoadLibraryDialog() {
        val current = if (!libraryFolderPath.isNullOrBlank()) "Path: $libraryFolderPath" else "Not configured"
        val options = mutableListOf<String>()
        options.add("Current")
        options.add("Change Folder...")
        options.add("Clear Library Folder")

        AlertDialog.Builder(this)
            .setTitle("EPUB Library")
            .setItems(options.toTypedArray()) { _, which ->
                when (options[which]) {
                    "Current" -> {
                        if (!libraryFolderPath.isNullOrBlank()) {
                            scanSavedLibraryFolder()
                        } else {
                            showError("No library folder configured yet")
                        }
                    }
                    "Change Folder..." -> showManualLibraryDialog()
                    "Clear Library Folder" -> {
                        libraryFolderPath = null
                        saveLibraryLocation()
                        downloads.clear()
                        bookAdapter.notifyDataSetChanged()
                        updateEmptyState()
                        toast("Library folder cleared")
                    }
                }
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showManualLibraryDialog() {
        val input = EditText(this)
        val libraryHint = libraryFolderPath ?: "/storage/emulated/0/Download"
        input.hint = libraryHint
        AlertDialog.Builder(this)
            .setTitle("Load EPUB Library")
            .setMessage("Enter a library folder path to scan.")
            .setView(input)
            .setPositiveButton("Scan") { _, _ ->
                val dir = input.text.toString().trim()
                if (dir.isBlank()) return@setPositiveButton
                val folder = java.io.File(dir)
                if (!folder.exists() || !folder.isDirectory) {
                    showError("Folder not found: $dir")
                    return@setPositiveButton
                }
                libraryFolderPath = folder.absolutePath
                saveLibraryLocation()
                scanManualEpubDir(folder)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun scanSavedLibraryFolder() {
        toast("Scanning saved library folder...")
        val path = libraryFolderPath
        if (path.isNullOrBlank()) {
            showError("No saved library folder path")
            return
        }
        val folder = java.io.File(path)
        if (!folder.exists() || !folder.isDirectory) {
            showError("Saved library folder not found: $path")
            return
        }
        scanManualEpubDir(folder)
    }

    private fun scanManualEpubDir(folder: java.io.File) {
        toast("Scanning ${folder.absolutePath}...")
        Thread {
            val resultJson = pythonBridge?.scanEpubDir(folder.absolutePath)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
                    val books = result.optJSONArray("books") ?: org.json.JSONArray()
                    downloads.clear()
                    val seen = mutableSetOf<String>()
                    for (i in 0 until books.length()) {
                        val b = books.getJSONObject(i)
                        val path = b.optString("path", "")
                        if (path.isNotBlank() && !seen.add(path)) continue
                        downloads.add(
                            BookItem(
                                title = b.optString("title", "untitled"),
                                author = b.optString("author", ""),
                                uriString = path,
                                lastModified = b.optLong("modified", 0L),
                                sizeBytes = b.optLong("size", 0L),
                                coverUriString = b.optString("cover", ""),
                                url = b.optString("url", ""),
                                chapters = b.optInt("chapters", 0)
                            )
                        )
                    }
                    downloads.sortByDescending { it.lastModified }
                    bookAdapter.notifyDataSetChanged()
                    updateEmptyState()
                    toast("Loaded ${downloads.size} EPUBs")
                    persistLibrary()
                } else {
                    showError("Scan failed: ${result?.optString("error") ?: "unknown"}")
                }
            }
        }.start()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_BOOK_DETAIL && resultCode == RESULT_OK && data != null) {
            val deleted = data.getBooleanExtra("deleted", false)
            if (deleted) {
                val position = selectedBook?.let { downloads.indexOf(it) } ?: -1
                if (position >= 0) {
                    downloads.removeAt(position)
                    bookAdapter.notifyDataSetChanged()
                    updateEmptyState()
                    persistLibrary()
                }
                return
            }

            val title = data.getStringExtra("title") ?: ""
            val author = data.getStringExtra("author") ?: ""
            val path = data.getStringExtra("path") ?: ""
            val modified = data.getLongExtra("modified", 0L)
            val book = selectedBook
            if (book != null && path.isNotBlank()) {
                val updated = book.copy(title = title, author = author, uriString = path, lastModified = modified)
                val index = findBookByIdentity(book)
                if (index >= 0) {
                    downloads[index] = updated
                } else {
                    downloads.add(updated)
                }
                bookAdapter.notifyDataSetChanged()
                persistLibrary()
            }
        }
    }

    private fun persistLibrary() {
        val books = org.json.JSONArray()
        for (b in downloads) {
            val obj = org.json.JSONObject()
            obj.put("title", b.title)
            obj.put("author", b.author)
            obj.put("url", b.url)
            obj.put("chapters", b.chapters)
            obj.put("path", b.uriString)
            obj.put("size", b.sizeBytes)
            obj.put("modified", b.lastModified)
            obj.put("cover", b.coverUriString)
            if (!b.sourceUriString.isNullOrBlank()) obj.put("source", b.sourceUriString)
            books.put(obj)
        }
        val payload = org.json.JSONObject().put("books", books).toString()
        val indexPath = getFilePath("library_index.json")
        Thread {
            val resultJson = pythonBridge?.saveLibraryIndex(indexPath, payload)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            if (result?.optBoolean("ok") != true) {
                runOnUiThread { toast("Save index failed") }
            }
        }.start()
    }

    private fun loadPersistedLibrary() {
        loadLibraryLocation()
        val indexPath = getFilePath("library_index.json")
        Thread {
            val resultJson = pythonBridge?.loadLibraryIndex(indexPath)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
                    val books = result.optJSONArray("books") ?: org.json.JSONArray()
                    downloads.clear()
                    for (i in 0 until books.length()) {
                        val b = books.getJSONObject(i)
                        downloads.add(
                            BookItem(
                                title = b.optString("title", "untitled"),
                                author = b.optString("author", ""),
                                uriString = b.optString("path", ""),
                                lastModified = b.optLong("modified", 0L),
                                sizeBytes = b.optLong("size", 0L),
                                coverUriString = b.optString("cover", ""),
                                url = b.optString("url", ""),
                                chapters = b.optInt("chapters", 0),
                                sourceUriString = b.optString("source", "").ifBlank { null }
                            )
                        )
                    }
                    applySort()
                    bookAdapter.notifyDataSetChanged()
                    updateEmptyState()
                }
            }
        }.start()
    }

    private fun applySort() {
        when (currentSort) {
            "title" -> downloads.sortBy { it.title.lowercase() }
            "author" -> downloads.sortBy { it.author.lowercase() }
            "chapters" -> downloads.sortByDescending { it.chapters }
            "modified" -> downloads.sortByDescending { it.lastModified }
            "size" -> downloads.sortByDescending { it.sizeBytes }
        }
    }

    private fun showSortDialog() {
        val options = arrayOf("Date Added", "Title", "Author", "Chapters", "Size")
        AlertDialog.Builder(this)
            .setTitle("Sort By")
            .setItems(options) { _, which ->
                currentSort = when (which) {
                    1 -> "title"
                    2 -> "author"
                    3 -> "chapters"
                    4 -> "size"
                    else -> "modified"
                }
                applySort()
                bookAdapter.notifyDataSetChanged()
            }
            .show()
    }

    private fun showSearchDialog() {
        val input = EditText(this)
        input.hint = "Search title or author"
        AlertDialog.Builder(this)
            .setTitle("Search")
            .setView(input)
            .setPositiveButton("Search") { _, _ ->
                val query = input.text.toString().trim().lowercase()
                if (query.isBlank()) {
                    applySort()
                    bookAdapter.notifyDataSetChanged()
                    return@setPositiveButton
                }
                val filtered = downloads.filter { book ->
                    book.title.lowercase().contains(query) || book.author.lowercase().contains(query)
                }
                bookAdapter = BookAdapter(filtered) { book ->
                    selectedBook = book
                    showBookOptionsDialog(book)
                }
                findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter
                updateEmptyState()
            }
            .setNegativeButton("Clear") { _, _ ->
                applySort()
                bookAdapter = BookAdapter(downloads) { book ->
                    selectedBook = book
                    showBookOptionsDialog(book)
                }
                findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter
                updateEmptyState()
            }
            .show()
    }

    private fun getFilePath(name: String): String {
        val dir = filesDir
        if (!dir.exists()) dir.mkdirs()
        return java.io.File(dir, name).absolutePath
    }

    private fun saveLibraryLocation() {
        val prefs = getSharedPreferences("fanficfare_prefs", MODE_PRIVATE)
        val editor = prefs.edit()
        if (!libraryFolderPath.isNullOrBlank()) {
            editor.putString("library_folder_path", libraryFolderPath)
        } else {
            editor.remove("library_folder_path")
        }
        editor.apply()
    }

    private fun loadLibraryLocation() {
        val prefs = getSharedPreferences("fanficfare_prefs", MODE_PRIVATE)
        libraryFolderPath = prefs.getString("library_folder_path", null)
    }

    @Throws(IOException::class)
    private fun copyToOutputDir(sourceFile: File, outputDir: String): String {
        return if (outputDir.startsWith("content://")) {
            val treeUri = Uri.parse(outputDir)
            val treeDoc = DocumentFile.fromTreeUri(this, treeUri)
                ?: throw IOException("Invalid output directory")
            val mimeType = "application/epub+zip"
            val newFile = treeDoc.createFile(mimeType, sourceFile.name)
                ?: throw IOException("Cannot create file in output directory")
            contentResolver.openOutputStream(newFile.uri)?.use { output ->
                sourceFile.inputStream().use { input ->
                    input.copyTo(output)
                }
            } ?: throw IOException("Cannot open output stream")
            newFile.uri.toString()
        } else {
            val destDir = File(outputDir)
            if (!destDir.exists()) destDir.mkdirs()
            val outFile = File(destDir, sourceFile.name)
            sourceFile.copyTo(outFile, overwrite = true)
            outFile.absolutePath
        }
    }

    private fun json(text: String): JSONObject? {
        return try { JSONObject(text) } catch (e: Exception) { null }
    }

    private fun refreshAllBooks() {
        val updatable = downloads.filter { it.url.isNotBlank() }
        if (updatable.isEmpty()) {
            toast("No updatable books")
            return
        }
        toast("Refreshing ${updatable.size} books...")
        Thread {
            var successCount = 0
            var failCount = 0
            for (book in updatable) {
                val resultJson = StorageBridge.withLocalEpub(this, book.uriString) { localPath ->
                    pythonBridge?.updateEpubFromPath(localPath.absolutePath, filesDir.absolutePath)
                }
                if (resultJson == null) {
                    failCount++
                    continue
                }
                val result = json(resultJson)
                if (result?.optBoolean("ok") == true) {
                    successCount++
                    val title = result.optString("title", book.title)
                    val internalPath = result.optString("path", "")
                    if (internalPath.isNotBlank()) {
                        try {
                            val source = File(internalPath)
                            if (source.exists() && source.isFile) {
                                val outputDir = SettingsActivity.getOutputDir(this@MainActivity)
                                val finalPath = copyToOutputDir(source, outputDir)
                                val author = result.optString("author", book.author)
                                runOnUiThread { refreshBookPath(book, title, author, finalPath) }
                            }
                        } catch (e: Exception) {
                            // ignore copy failures in batch mode
                        }
                    }
                } else {
                    failCount++
                }
            }
            runOnUiThread {
                toast("Refresh complete. Updated: $successCount, Failed: $failCount")
                persistLibrary()
            }
        }.start()
    }
}
