package com.example.fanficfare

import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.fanficfare.adapter.BookAdapter
import com.example.fanficfare.model.BookItem
import com.chaquo.python.Python
import org.json.JSONObject

class MainActivity : AppCompatActivity() {

    private val downloads = mutableListOf<BookItem>()
    private lateinit var bookAdapter: BookAdapter
    private var pythonBridge: PythonBridge? = null
    private var selectedBook: BookItem? = null
    private var currentSort: String = "modified"

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
            ensureStoragePermission {
                showLoadLibraryDialog()
            }
        }

        updateEmptyState()
        loadPersistedLibrary()

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
        options.add("Delete")
        options.add("Show Path")

        AlertDialog.Builder(this)
            .setTitle(book.title.ifBlank { "Book" })
            .setItems(options.toTypedArray()) { _, which ->
                val choice = options[which]
                when (choice) {
                    "Update" -> updateBook(book)
                    "Force Download" -> forceDownloadBook(book)
                    "Delete" -> deleteBook(book)
                    "Show Path" -> showPath(book)
                }
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun updateBook(book: BookItem) {
        val url = book.url
        if (url.isBlank()) {
            setStatus("No URL found for this book")
            return
        }
        setStatus("Updating...")
        Thread {
            val resultJson = pythonBridge?.updateEpubFromPath(book.uriString, filesDir.absolutePath)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
                    val title = result.optString("title", book.title)
                    val path = result.optString("path", "")
                    setStatus("Updated: $title")
                    if (path.isNotBlank()) {
                        refreshBookPath(book, title, path)
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
            val resultJson = pythonBridge?.forceDownloadFromEpub(book.uriString, filesDir.absolutePath)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
                    val title = result.optString("title", book.title)
                    val path = result.optString("path", "")
                    setStatus("Downloaded: $title")
                    if (path.isNotBlank()) {
                        refreshBookPath(book, title, path)
                    }
                } else {
                    setStatus("Download failed: ${result?.optString("error") ?: "unknown"}")
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
                    val resultJson = pythonBridge?.deleteEpub(book.uriString)
                        ?: """{"ok":false,"error":"bridge missing"}"""
                    val result = json(resultJson)
                    runOnUiThread {
                        if (result?.optBoolean("ok") == true) {
                            downloads.remove(book)
                            bookAdapter.notifyDataSetChanged()
                            updateEmptyState()
                            setStatus("Deleted")
                        } else {
                            showError("Delete failed: ${result?.optString("error") ?: "unknown"}")
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

    private fun refreshBookPath(oldBook: BookItem, title: String, path: String) {
        val index = downloads.indexOf(oldBook)
        if (index >= 0) {
            val updated = oldBook.copy(
                title = title,
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
                        val path = result.optString("path", "")
                        setStatus("Saved: $title")
                        if (path.isNotBlank()) {
                            downloads.add(0, BookItem(title, "", path, System.currentTimeMillis(), 0))
                            bookAdapter.notifyDataSetChanged()
                            updateEmptyState()
                            persistLibrary()
                        }
                    } else {
                        showError("Download failed: ${result?.optString("error") ?: "unknown"}")
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
    }

    private fun showLoadLibraryDialog() {
        val input = EditText(this)
        input.hint = "Folder path"
        AlertDialog.Builder(this)
            .setTitle("Load EPUB Library")
            .setView(input)
            .setPositiveButton("Scan") { _, _ ->
                val dir = input.text.toString().trim()
                if (dir.isBlank()) return@setPositiveButton
                setStatus("Scanning...")
                Thread {
                    val resultJson = pythonBridge?.scanEpubDir(dir) ?: """{"ok":false,"error":"bridge missing"}"""
                    val result = json(resultJson)
                    runOnUiThread {
                        if (result?.optBoolean("ok") == true) {
                            val books = result.optJSONArray("books") ?: org.json.JSONArray()
                            downloads.clear()
                            for (i in 0 until books.length()) {
                                val b = books.getJSONObject(i)
                                val title = b.optString("title", "untitled")
                                val author = b.optString("author", "")
                                val url = b.optString("url", "")
                                val chapters = b.optInt("chapters", 0)
                                val path = b.optString("path", "")
                                val size = b.optLong("size", 0L)
                                val modified = b.optLong("modified", 0L)
                                val cover = b.optString("cover", "")
                                downloads.add(BookItem(title, author, path, modified, size, coverUriString = cover, url = url, chapters = chapters))
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
            .setNegativeButton("Cancel", null)
            .show()
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
                val resultJson = pythonBridge?.updateEpubFromPath(book.uriString, SettingsActivity.getOutputDir(this))
                    ?: """{"ok":false,"error":"bridge missing"}"""
                val result = json(resultJson)
                if (result?.optBoolean("ok") == true) {
                    successCount++
                    val title = result.optString("title", book.title)
                    val path = result.optString("path", "")
                    if (path.isNotBlank()) {
                        runOnUiThread { refreshBookPath(book, title, path) }
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
