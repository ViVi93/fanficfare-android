package com.example.fanficfare

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.DocumentsContract
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
    private var libraryFolderUri: android.net.Uri? = null
    private var libraryFolderPath: String? = null
    private val REQUEST_BOOK_DETAIL = 1003
    private lateinit var pickLibraryFolder: androidx.activity.result.ActivityResultLauncher<android.net.Uri?>

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
                if (hasStoragePermission()) action() else setStatus("Storage permission denied")
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
                setStatus("Python init failed: ${e.message}")
            }
        }
        pythonBridge = PythonBridge(this)
        pythonBridge?.getInitError()?.let { error ->
            setStatus("Bridge init failed: $error")
        }
        pythonBridge?.getFanFicFareError()?.let { error ->
            setStatus("FanFicFare init failed: $error")
        }

        bookAdapter = BookAdapter(downloads) { book ->
            selectedBook = book
            showBookOptionsDialog(book)
        }
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).layoutManager = LinearLayoutManager(this)
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter

        findViewById<com.google.android.material.floatingactionbutton.FloatingActionButton>(R.id.fabPickFolder).setOnClickListener {
            showDownloadDialog()
        }
        findViewById<com.google.android.material.floatingactionbutton.FloatingActionButton>(R.id.fabLoadLibrary).setOnClickListener {
            showLoadLibraryDialog()
        }

        updateEmptyState()
        loadPersistedLibrary()

        pickLibraryFolder = registerForActivityResult(
            androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()
        ) { uri ->
            if (uri != null) {
                libraryFolderUri = uri
                libraryFolderPath = null
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
                saveLibraryLocation()
                setStatus("Scanning folder...")
                Thread {
                    val epubs = discoverEpubsFromTree(uri)
                    runOnUiThread {
                        if (epubs.isEmpty()) {
                            showError("No EPUBs found in selected folder")
                        } else {
                            scanImportedEpubs(epubs)
                        }
                    }
                }.start()
            }
        }

        findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar).setOnMenuItemClickListener { item ->
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

    private fun setStatus(text: String) {
        findViewById<TextView>(R.id.textStatus).text = text
    }

    private fun toast(text: String) {
        android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show()
    }

    private fun showError(message: String) {
        setStatus(message)
        toast(message)
    }

    fun getPythonBridge(): PythonBridge? = pythonBridge

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
        options.add("Show Path")

        AlertDialog.Builder(this)
            .setTitle(book.title.ifBlank { "Book" })
            .setItems(options.toTypedArray()) { _, which ->
                val choice = options[which]
                when (choice) {
                    "Update" -> updateBook(book)
                    "Force Download" -> forceDownloadBook(book)
                    "Details" -> openBookDetail(book)
                    "Delete" -> deleteBook(book)
                    "Show Path" -> showPath(book)
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
            .putExtra("cover", book.coverUriString)
            .putExtra("url", book.url)
            .putExtra("chapters", book.chapters)
        startActivityForResult(intent, REQUEST_BOOK_DETAIL)
    }

    private fun updateBook(book: BookItem) {
        val url = book.url
        if (url.isBlank()) {
            setStatus("No URL found for this book")
            return
        }
        setStatus("Updating...")
        Thread {
            val resultJson = StorageBridge.withLocalEpub(this, book.uriString) { localPath ->
                pythonBridge?.updateEpubFromPath(localPath.absolutePath, filesDir.absolutePath)
            } ?: run {
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
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
                                    coverUriString = result.optString("cover", book.coverUriString ?: ""),
                                    url = result.optString("url", book.url ?: ""),
                                    chapters = result.optInt("chapters", 0)
                                )
                                val idx = findBookByIdentity(book)
                                if (idx >= 0) downloads[idx] = updated else downloads.add(0, updated)
                                bookAdapter.notifyDataSetChanged()
                                setStatus("Updated: $title")
                                persistLibrary()
                            } else {
                                setStatus("Updated: $title")
                                persistLibrary()
                            }
                        } catch (e: Exception) {
                            showError("Update failed: ${e.message}")
                        }
                    } else {
                        setStatus("Updated: $title")
                        persistLibrary()
                    }
                } else {
                    showError("Update failed: ${result?.optString("error") ?: "unknown"}")
                }
            }
        }.start()
    }

    private fun forceDownloadBook(book: BookItem) {
        val url = book.url
        if (url.isBlank()) {
            setStatus("No URL found for this book")
            return
        }
        setStatus("Force downloading...")
        Thread {
            val resultJson = StorageBridge.withLocalEpub(this, book.uriString) { localPath ->
                pythonBridge?.forceDownloadFromEpub(localPath.absolutePath, filesDir.absolutePath)
            } ?: run {
                runOnUiThread { showError("Cannot read EPUB from this location") }
                return@Thread
            }
            runOnUiThread {
                try {
                    val result = org.json.JSONObject(resultJson)
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
                                        coverUriString = result.optString("cover", book.coverUriString ?: ""),
                                        url = result.optString("url", book.url ?: ""),
                                        chapters = result.optInt("chapters", 0)
                                    )
                                    val idx = findBookByIdentity(book)
                                    if (idx >= 0) downloads[idx] = updated else downloads.add(0, updated)
                                    bookAdapter.notifyDataSetChanged()
                                    setStatus("Downloaded: $title")
                                    persistLibrary()
                                } else {
                                    setStatus("Downloaded: $title")
                                    persistLibrary()
                                }
                            } catch (e: Exception) {
                                showError("Download failed: ${e.message ?: "copy/output error"}")
                            }
                        } else {
                            setStatus("Downloaded: $title")
                            persistLibrary()
                        }
                    } else {
                        val errorMsg = result.optString("error") ?: "unknown"
                        val detail = result.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        showError("Download failed: $fullMsg")
                    }
                } catch (e: Exception) {
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
                            setStatus("Deleted")
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

    private fun showPath(book: BookItem) {
        AlertDialog.Builder(this)
            .setTitle("Path")
            .setMessage(book.uriString)
            .setPositiveButton("OK", null)
            .show()
    }

    private fun refreshBookPath(oldBook: BookItem, title: String, author: String, path: String) {
        val index = downloads.indexOf(oldBook)
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
            setStatus("Downloading...")
            Thread {
                val resultJson = try {
                    pythonBridge?.fanficfareDownload(url, filesDir.absolutePath)
                        ?: """{"ok":false,"error":"bridge missing"}"""
                } catch (e: Exception) {
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
                            setStatus("Saved: $title")
                            val author = result.optString("author", "")
                            val url = result.optString("url", "")
                            val chapters = result.optInt("chapters", 0)
                            val cover = result.optString("cover", "")
                            val size = result.optLong("size", 0L)
                            val modified = result.optLong("modified", 0L)
                            val newBook = BookItem(title, author, finalPath, modified, size, cover, url, chapters)
                            val existing = findBookByIdentity(newBook)
                            if (existing >= 0) {
                                downloads[existing] = newBook
                            } else {
                                downloads.add(0, newBook)
                            }
                            bookAdapter.notifyDataSetChanged()
                            updateEmptyState()
                            persistLibrary()
                        } catch (e: Exception) {
                            showError("Download failed: ${e.message}")
                        }
                    } else {
                        val errorMsg = result?.optString("error") ?: "unknown"
                        val detail = result?.optString("detail")
                        val fullMsg = if (!detail.isNullOrBlank()) "$errorMsg\n$detail" else errorMsg
                        showError("Download failed: $fullMsg")
                    }
                }
            }.start()
        }
        view.findViewById<android.widget.Button>(R.id.buttonUpdate).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            setStatus("Updating...")
            Thread {
                val resultJson = try {
                    pythonBridge?.fanficfareMetadata(url)
                        ?: """{"ok":false,"error":"bridge missing"}"""
                } catch (e: Exception) {
                    """{"ok":false,"error":${JSONObject().put("msg", e.message).toString()}}"""
                }
                val result = json(resultJson)
                runOnUiThread {
                    if (result?.optBoolean("ok") == true) {
                        setStatus("Metadata fetched")
                    } else {
                        showError("Update check failed: ${result?.optString("error") ?: "unknown"}")
                    }
                }
            }.start()
        }
        AlertDialog.Builder(this)
            .setTitle("FanFicFare")
            .setView(view)
            .setNegativeButton("Close", null)
            .show()
        view.findViewById<android.widget.Button>(R.id.buttonDiagnose).setOnClickListener {
            setStatus("Diagnosing...")
            Thread {
                val resultJson = pythonBridge?.diagnoseFanFicFareImports()
                    ?: """{"ok":false,"error":"bridge missing"}"""
                val result = json(resultJson)
                runOnUiThread {
                    val sb = StringBuilder()
                    sb.append("Diagnostics:\n")
                    val arr = result?.optJSONArray("results")
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
                    val diag = sb.toString().trim()
                    setStatus(diag)
                    showError(diag)
                }
            }.start()
        }
    }

    private fun showLoadLibraryDialog() {
        val current = when {
            libraryFolderUri != null -> "SAF: ${libraryFolderUri}"
            !libraryFolderPath.isNullOrBlank() -> "Path: $libraryFolderPath"
            else -> "Not configured"
        }
        val options = mutableListOf<String>()
        options.add("Pick Folder...")
        options.add("Enter Path Manually...")
        options.add("Current: $current")
        options.add("Clear Library Folder")

        AlertDialog.Builder(this)
            .setTitle("EPUB Library")
            .setItems(options.toTypedArray()) { _, which ->
                when (options[which]) {
                    "Pick Folder..." -> {
                        try {
                            pickLibraryFolder.launch(null)
                        } catch (e: Exception) {
                            showFallbackLibraryDialog()
                        }
                    }
                    "Enter Path Manually..." -> showFallbackLibraryDialog()
                    "Current: $current" -> {
                        if (libraryFolderUri != null || !libraryFolderPath.isNullOrBlank()) {
                            scanSavedLibraryFolder()
                        } else {
                            showError("No library folder configured yet")
                        }
                    }
                    "Clear Library Folder" -> {
                        libraryFolderUri = null
                        libraryFolderPath = null
                        saveLibraryLocation()
                        setStatus("Library folder cleared")
                    }
                }
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun scanSavedLibraryFolder() {
        setStatus("Scanning saved library folder...")
        Thread {
            val epubs = if (libraryFolderUri != null) {
                try {
                    discoverEpubsFromTree(libraryFolderUri!!)
                } catch (e: Exception) {
                    runOnUiThread {
                        showError("Cannot access SAF library folder: ${e.message ?: "access denied"}")
                    }
                    return@Thread
                }
            } else {
                val folder = java.io.File(libraryFolderPath!!)
                if (!folder.exists() || !folder.isDirectory) {
                    runOnUiThread { showError("Saved library folder not found: $libraryFolderPath") }
                    return@Thread
                }
                folder.walkTopDown().filter { it.isFile && it.extension.equals("epub", ignoreCase = true) }.toList()
            }
            runOnUiThread {
                if (epubs.isEmpty()) {
                    showError("No EPUBs found in saved library folder")
                } else {
                    scanImportedEpubs(epubs)
                }
            }
        }.start()
    }

    private fun showFallbackLibraryDialog() {
        val input = EditText(this)
        val libraryHint = libraryFolderPath ?: "/storage/emulated/0/Download"
        input.hint = libraryHint
        AlertDialog.Builder(this)
            .setTitle("Load EPUB Library")
            .setMessage("Folder picker unavailable. Enter a library folder path manually, or grant All Files Access in Settings.")
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
                libraryFolderUri = null
                saveLibraryLocation()
                val files = folder.walkTopDown().filter { it.isFile && it.extension.equals("epub", ignoreCase = true) }.toList()
                if (files.isEmpty()) {
                    showError("No EPUBs found in $dir")
                } else {
                    scanImportedEpubs(files)
                }
            }
            .setNeutralButton("Settings") { _, _ ->
                startActivity(android.content.Intent(this, SettingsActivity::class.java))
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun scanOriginalEpubs(sourceDir: java.io.File) {
        setStatus("Scanning ${sourceDir.absolutePath}...")
        Thread {
            val resultJson = pythonBridge?.scanEpubDir(sourceDir.absolutePath)
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
                    setStatus("Loaded ${downloads.size} EPUBs")
                    persistLibrary()
                } else {
                    showError("Scan failed: ${result?.optString("error") ?: "unknown"}")
                }
            }
        }.start()
    }

    private fun discoverEpubsFromTree(rootUri: android.net.Uri): List<java.io.File> {
        val resolver = contentResolver
        val picked = mutableListOf<java.io.File>()
        val outDir = java.io.File(filesDir, "imported").apply { mkdirs() }

        val treeDoc = androidx.documentfile.provider.DocumentFile.fromTreeUri(this, rootUri)
            ?: throw IllegalArgumentException("Cannot resolve tree URI: $rootUri")
        if (!treeDoc.canRead()) {
            throw IllegalArgumentException("Tree URI is not readable: $rootUri")
        }

        val queue = ArrayDeque<androidx.documentfile.provider.DocumentFile>()
        queue.add(treeDoc)

        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            try {
                val children = current.listFiles()
                for (child in children) {
                    try {
                        if (child.isDirectory) {
                            queue.add(child)
                        } else if (child.name?.lowercase()?.endsWith(".epub") == true) {
                            val dest = java.io.File(outDir, child.name!!)
                            try {
                                resolver.openInputStream(child.uri)?.use { input ->
                                    java.io.FileOutputStream(dest).use { output ->
                                        input.copyTo(output)
                                    }
                                }
                                picked.add(dest)
                            } catch (e: Exception) {
                                // skip unreadable file but continue traversal
                            }
                        }
                    } catch (e: Exception) {
                        // skip unreadable tree node but continue traversal
                    }
                }
            } catch (e: Exception) {
                throw IllegalArgumentException("Cannot list children of URI node: ${e.message ?: e}")
            }
        }
        return picked
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
                val index = downloads.indexOf(book)
                if (index >= 0) {
                    downloads[index] = updated
                }
                bookAdapter.notifyDataSetChanged()
                persistLibrary()
            }
        }
    }

    private fun scanImportedEpubs(files: List<java.io.File>) {
        val importDir = java.io.File(filesDir, "imported").apply { mkdirs() }
        setStatus("Importing ${files.size} files...")
        Thread {
            val copied = mutableListOf<java.io.File>()
            files.forEach { src ->
                val dest = java.io.File(importDir, src.name)
                try {
                    src.copyTo(dest, overwrite = true)
                    copied.add(dest)
                } catch (e: Exception) {
                    // skip
                }
            }
            runOnUiThread {
                if (copied.isEmpty()) {
                    showError("Could not import any files")
                } else {
                    setStatus("Scanning ${copied.size} files...")
                }
            }
            val resultJson = pythonBridge?.scanEpubDir(importDir.absolutePath)
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
                    setStatus("Loaded ${downloads.size} EPUBs")
                    persistLibrary()
                } else {
                    showError("Scan failed: ${result?.optString("error") ?: "unknown"}")
                }
            }
        }.start()
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
            books.put(obj)
        }
        val payload = org.json.JSONObject().put("books", books).toString()
        val indexPath = getFilePath("library_index.json")
        Thread {
            val resultJson = pythonBridge?.saveLibraryIndex(indexPath, payload)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            if (result?.optBoolean("ok") != true) {
                runOnUiThread { setStatus("Save index failed") }
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
                                chapters = b.optInt("chapters", 0)
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
        if (libraryFolderUri != null) {
            editor.putString("library_folder_uri", libraryFolderUri.toString())
            editor.remove("library_folder_path")
        } else if (!libraryFolderPath.isNullOrBlank()) {
            editor.putString("library_folder_path", libraryFolderPath)
            editor.remove("library_folder_uri")
        } else {
            editor.remove("library_folder_uri")
            editor.remove("library_folder_path")
        }
        editor.apply()
    }

    private fun loadLibraryLocation() {
        val prefs = getSharedPreferences("fanficfare_prefs", MODE_PRIVATE)
        libraryFolderUri = prefs.getString("library_folder_uri", null)?.let { android.net.Uri.parse(it) }
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
            setStatus("No updatable books")
            return
        }
        setStatus("Refreshing ${updatable.size} books...")
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
                setStatus("Refresh complete. Updated: $successCount, Failed: $failCount")
                persistLibrary()
            }
        }.start()
    }
}
