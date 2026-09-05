package com.example.fanficfare

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.fanficfare.adapter.BookAdapter
import com.example.fanficfare.model.BookItem
import com.chaquo.python.Python
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var bookAdapter: BookAdapter
    private var pythonBridge: PythonBridge? = null
    private var selectedBook: BookItem? = null
    private val REQUEST_BOOK_DETAIL = 1003
    private val REQUEST_POST_NOTIFICATIONS = 1004

    private lateinit var viewModel: LibraryViewModel
    private var libraryFolderPath: String? = null
    private var lastTerminalToastJobId: Long? = null
    private var selectionMenu: Menu? = null
    private var baseMenu: Menu? = null

    private val statusProgress get() = findViewById<android.widget.ProgressBar>(R.id.status_progress)
    private val statusText get() = findViewById<TextView>(R.id.status_text)
    private val statusContainer get() = findViewById<android.view.ViewGroup>(R.id.status_container)

    override fun onCreate(savedInstanceState: Bundle?) {
        try {
            val t0 = System.currentTimeMillis()
            super.onCreate(savedInstanceState)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.VANILLA_ICE_CREAM) {
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, true)
            }
            setContentView(R.layout.activity_main)
            supportActionBar?.hide()
            DiagnosticLog.append(this, "Main.Startup", "begin elapsed=${System.currentTimeMillis() - t0}")
            if (!Python.isStarted()) {
                try {
                    Python.start(com.chaquo.python.android.AndroidPlatform(this))
                } catch (e: Exception) {
                    DiagnosticLog.append(this, "Main.Startup", "python_failed")
                }
            }
            DiagnosticLog.append(this, "Main.Startup", "python_ready elapsed=${System.currentTimeMillis() - t0}")

            pythonBridge = PythonBridge(this)
            pythonBridge?.getInitError()?.let { error ->
                DiagnosticLog.append(this, "Main.Startup", "bridge_init_failed")
            }
            pythonBridge?.getFanFicFareError()?.let { error ->
                DiagnosticLog.append(this, "Main.Startup", "fanficfare_init_failed")
            }
            pythonBridge?.initialize(SettingsActivity.getConfigDir(this).absolutePath)
            DiagnosticLog.append(this, "Main.Startup", "bridge_ready elapsed=${System.currentTimeMillis() - t0}")

            val repository = BookRepository(this)
            DiagnosticLog.append(this, "Main.Startup", "repository_ready elapsed=${System.currentTimeMillis() - t0}")

            viewModel = ViewModelProvider(this, ViewModelFactory(repository))[LibraryViewModel::class.java]
            DiagnosticLog.append(this, "Main.Startup", "viewmodel_ready elapsed=${System.currentTimeMillis() - t0}")

            android.util.Log.d("FFF-UI-OBS", "MainActivity direct observer repo=${true}")
            repository.jobDao.observeAll().observe(this) { jobs ->
                android.util.Log.d("FFF-UI-OBS", "MainActivity direct observeAll count=${jobs.size}")
                val latest = jobs.maxByOrNull { it.createdAt }
                android.util.Log.d("FFF-UI-OBS", "MainActivity direct latest job=${latest?.id} status=${latest?.status}")
                if (latest == null) {
                    statusContainer?.visibility = android.view.View.GONE
                    return@observe
                }
                val text = when (latest.status) {
                    "queued" -> "Queued"
                    "running" -> "Running..."
                    "success" -> "✓ Complete"
                    "failed" -> "✗ Failed"
                    "cancelled" -> "⏹ Cancelled"
                    else -> latest.status.replaceFirstChar { it.uppercase() }
                }
                statusContainer?.visibility = android.view.View.VISIBLE
                statusProgress?.visibility = if (latest.status == "running") android.view.View.VISIBLE else android.view.View.GONE
                statusText?.text = text
            }

            bookAdapter = BookAdapter(viewModel.getBooksSnapshot(), { book ->
                selectedBook = book
                if (bookAdapter.isSelectionMode()) {
                    bookAdapter.toggleSelection(book)
                    updateSelectionUi()
                } else {
                    showBookOptionsDialog(book)
                }
            }, { book ->
                if (!bookAdapter.isSelectionMode()) {
                    bookAdapter.enterSelectionMode(book)
                    updateSelectionUi()
                }
            })
            findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).layoutManager = LinearLayoutManager(this)
            findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter

            viewModel.visibleBooks.observe(this) { books ->
                if (books.isNotEmpty()) {
                    syncBooks(books)
                }
            }

            DiagnosticLog.append(this, "Main.Startup", "load_persisted_library_begin elapsed=${System.currentTimeMillis() - t0}")
            loadPersistedLibrary()
            DiagnosticLog.append(this, "Main.Startup", "load_persisted_library_end elapsed=${System.currentTimeMillis() - t0}")
            ensureNotificationPermission()
            DiagnosticLog.append(this, "Main.Startup", "complete elapsed=${System.currentTimeMillis() - t0}")

            viewModel.uiJobState.observe(this) { state ->
                if (state == null) {
                    statusContainer?.visibility = android.view.View.VISIBLE
                    statusProgress?.visibility = android.view.View.GONE
                    statusText?.text = "Ready"
                    return@observe
                }
                statusContainer?.visibility = android.view.View.VISIBLE
                statusProgress?.isIndeterminate = state.indeterminate
                statusProgress?.visibility = if (state.indeterminate) android.view.View.VISIBLE else android.view.View.GONE
                statusText?.text = when {
                    state.finished && state.status == "success" -> "✓ Complete"
                    state.finished && state.status == "failed" -> "✗ Failed"
                    state.finished && state.status == "cancelled" -> "⏹ Cancelled"
                    state.phase.isBlank() -> "Ready"
                    else -> "${state.phase.replaceFirstChar { it.uppercase() }}..."
                }
                if (state.finished && state.status != state.phase) {
                    statusText?.text = state.phase
                }
                if (state.finished && lastTerminalToastJobId != state.jobId) {
                    lastTerminalToastJobId = state.jobId
                    when (state.status) {
                        "success" -> toast("${humanizeOperation(state.type)} complete")
                        "failed" -> toast("${humanizeOperation(state.type)} failed")
                        "cancelled" -> toast("${humanizeOperation(state.type)} cancelled")
                    }
                }
                if (state.finished) {
                    // Worker already inserted/updated the book; avoid reloading from disk
                }
                if (!state.finished) {
                    lastTerminalToastJobId = null
                }
            }
            val dao = (viewModel as? LibraryViewModel)?.let { 
                try { (it as Any).javaClass.getDeclaredField("repository").let { f -> f.isAccessible = true; f.get(it) } } catch (e: Exception) { null }
            } as? com.example.fanficfare.BookRepository
            android.util.Log.d("FFF-UI-OBS", "MainActivity direct observer repo=${dao != null}")
            dao?.jobDao?.observeAll()?.observe(this) { jobs ->
                android.util.Log.d("FFF-UI-OBS", "MainActivity direct observeAll count=${jobs.size}")
                val latest = jobs.maxByOrNull { it.createdAt }
                android.util.Log.d("FFF-UI-OBS", "MainActivity direct latest job=${latest?.id} status=${latest?.status}")
                if (latest == null) {
                    statusContainer?.visibility = android.view.View.GONE
                    return@observe
                }
                val text = when (latest.status) {
                    "queued" -> "Queued"
                    "running" -> "Running..."
                    "success" -> "✓ Complete"
                    "failed" -> "✗ Failed"
                    "cancelled" -> "⏹ Cancelled"
                    else -> latest.status.replaceFirstChar { it.uppercase() }
                }
                statusContainer?.visibility = android.view.View.VISIBLE
                statusProgress?.visibility = if (latest.status == "running") android.view.View.VISIBLE else android.view.View.GONE
                statusText?.text = text
            }

            val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
            toolbar.inflateMenu(R.menu.main_menu)
            baseMenu = toolbar.menu
            toolbar.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    R.id.action_download -> {
                        showDownloadDialog()
                        true
                    }
                    R.id.action_add_from_page -> {
                        startActivity(Intent(this, AddFromPageActivity::class.java))
                        true
                    }
                    R.id.action_select -> {
                        enterSelectionMode()
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
                    R.id.action_update_selected -> {
                        updateSelectedBooks()
                        true
                    }
                    R.id.action_cancel_selection -> {
                        clearSelectionMode()
                        true
                    }
                    R.id.action_cancel_download -> {
                        DiagnosticLog.append(this, "Main.Cancel", "cancel_pressed")
                        toast("Cancelling download...")
                        viewModel.cancelCurrentDownload()
                        true
                    }
                    else -> false
                }
            }

            handleSharedUrl(intent)
        } catch (e: Throwable) {
            android.util.Log.e("MainActivity", "onCreate crash", e)
            runOnUiThread {
                AlertDialog.Builder(this)
                    .setTitle("Startup Error")
                    .setMessage("${e.javaClass.simpleName}: ${e.message ?: "null"}")
                    .setPositiveButton("OK") { _, _ -> finish() }
                    .show()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
    }

    private fun handleSharedUrl(intent: Intent) {
        if (intent.action != Intent.ACTION_SEND || intent.type != "text/plain") return
        val url = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
        if (url.isBlank() || !url.startsWith("http")) return
        DiagnosticLog.append(this, "Main.Shared", "shared_url=$url")
        toast("Sharing download: ${android.net.Uri.parse(url).host ?: url}")
        viewModel.enqueueDownload(url)
        DiagnosticLog.append(this, "Main.Shared", "enqueued_download url=$url")
    }

    override fun onCreateOptionsMenu(menu: Menu?): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    private fun toast(text: String) {
        android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show()
    }

    private fun ensureNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), REQUEST_POST_NOTIFICATIONS)
            }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_POST_NOTIFICATIONS) {
            // silently ignore; Worker continues without notification if denied
        }
    }

    private fun showError(message: String) {
        toast(message)
    }

    private fun getPythonBridge(): PythonBridge? = pythonBridge

    private fun updateEmptyState() {
    }

    private fun syncBooks(books: List<BookItem>) {
        bookAdapter = BookAdapter(books, { book ->
            selectedBook = book
            if (bookAdapter.isSelectionMode()) {
                bookAdapter.toggleSelection(book)
                updateSelectionUi()
            } else {
                showBookOptionsDialog(book)
            }
        }, { book ->
            if (!bookAdapter.isSelectionMode()) {
                bookAdapter.enterSelectionMode(book)
                updateSelectionUi()
            }
        })
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter
        updateEmptyState()
    }

    private fun enterSelectionMode() {
        bookAdapter.enterSelectionMode(viewModel.getBooksSnapshot().firstOrNull() ?: return)
        updateSelectionUi()
        swapMenu(true)
    }

    private fun updateSelectionUi() {
        val count = bookAdapter.getSelectedBooks().size
        if (count == 0 || !bookAdapter.isSelectionMode()) {
            clearSelectionMode()
            return
        }
        statusContainer?.visibility = android.view.View.VISIBLE
        statusProgress?.visibility = android.view.View.GONE
        statusText?.text = "$count selected"
    }

    private fun clearSelectionMode() {
        bookAdapter.clearSelection()
        statusContainer?.visibility = android.view.View.GONE
        swapMenu(false)
    }

    private fun updateSelectedBooks() {
        val selected = bookAdapter.getSelectedBooks().filter { it.url.isNotBlank() }
        if (selected.isEmpty()) {
            toast("No updatable books selected")
            return
        }
        toast("Updating ${selected.size} books...")
        for (book in selected) {
            viewModel.enqueueUpdate(0, book.uriString)
        }
        clearSelectionMode()
    }

    private fun swapMenu(selecting: Boolean) {
        val menu = if (selecting) R.menu.selection_menu else R.menu.main_menu
        val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
        toolbar.menu.clear()
        toolbar.inflateMenu(menu)
    }

    override fun onBackPressed() {
        if (bookAdapter.isSelectionMode()) {
            clearSelectionMode()
            return
        }
        super.onBackPressed()
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
        viewModel.enqueueUpdate(0, book.uriString)
        DiagnosticLog.append(this, "Main.Update", "enqueued path=${book.uriString}")
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
        viewModel.enqueueForceDownload(0, book.uriString)
        DiagnosticLog.append(this, "Main.ForceDownload", "enqueued path=${book.uriString}")
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
                            viewModel.remove(book)
                            syncBooks(viewModel.getBooksSnapshot())
                            updateEmptyState()
                            viewModel.saveLibrary()
                            toast("Deleted")
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
        val updated = oldBook.copy(
            title = title,
            author = author,
            uriString = path,
            lastModified = System.currentTimeMillis()
        )
        viewModel.updateBook(oldBook, updated)
        syncBooks(viewModel.getBooksSnapshot())
    }

    private fun showDownloadDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_download, null)
        val input = view.findViewById<EditText>(R.id.inputUrl)
        view.findViewById<android.widget.Button>(R.id.buttonDownload).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            toast("Downloading...")
            viewModel.enqueueDownload(url)
            DiagnosticLog.append(this, "Main.Download", "enqueued url=$url")
        }
        view.findViewById<android.widget.Button>(R.id.buttonUpdate).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            toast("Checking metadata...")
            lifecycleScope.launch {
                viewModel.enqueueMetadata(url)
                DiagnosticLog.append(this@MainActivity, "Main.Update", "enqueued_metadata url=$url")
            }
        }
        AlertDialog.Builder(this)
            .setView(view)
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showLoadLibraryDialog() {
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
                        viewModel.clearLibrary()
                        syncBooks(viewModel.getBooksSnapshot())
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
        android.util.Log.d("FFF-Dup", "scanManualEpubDir start path=${folder.absolutePath}")
        Thread {
            val resultJson = pythonBridge?.scanEpubDir(folder.absolutePath)
                ?: """{"ok":false,"error":"bridge missing"}"""
            val result = json(resultJson)
            runOnUiThread {
                if (result?.optBoolean("ok") == true) {
                    val books = result.optJSONArray("books") ?: org.json.JSONArray()
                    android.util.Log.d("FFF-Dup", "scanManualEpubDir scannedCount=${books.length()}")
                    val list = mutableListOf<BookItem>()
                    val seen = mutableSetOf<String>()
                    for (i in 0 until books.length()) {
                        val b = books.getJSONObject(i)
                        val path = b.optString("path", "")
                        if (path.isNotBlank() && !seen.add(path)) continue
                        list.add(
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
                    list.sortByDescending { it.lastModified }
                    for (book in list) {
                        viewModel.addOrUpdate(book)
                    }
                    syncBooks(viewModel.getBooksSnapshot())
                    updateEmptyState()
                    toast("Loaded ${list.size} EPUBs")
                    viewModel.saveLibrary()
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
                val position = selectedBook?.let { viewModel.findByIdentity(it) } ?: -1
                if (position >= 0) {
                    val current = viewModel.getBooksSnapshot().toMutableList()
                    current.removeAt(position)
                    viewModel.setBooks(current)
                    syncBooks(viewModel.getBooksSnapshot())
                    updateEmptyState()
                    viewModel.saveLibrary()
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
                viewModel.updateBook(book, updated)
                syncBooks(viewModel.getBooksSnapshot())
                viewModel.saveLibrary()
            }
        }
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

    private fun loadPersistedLibrary() {
        loadLibraryLocation()
        val success = viewModel.loadLibrary()
        if (success) {
            viewModel.setSort(viewModel.getCurrentSort())
        }
        syncBooks(viewModel.getBooksSnapshot())
        updateEmptyState()
    }

    private fun copyToOutputDir(sourceFile: File, outputDir: String): String {
        return StorageBridge.copyToOutputDir(this, sourceFile, outputDir)
    }

    private fun json(text: String): JSONObject? {
        return try { JSONObject(text) } catch (e: Exception) { null }
    }

    private fun applySort(books: List<BookItem>, sort: String): List<BookItem> {
        return when (sort) {
            "title" -> books.sortedBy { it.title.lowercase() }
            "author" -> books.sortedBy { it.author.lowercase() }
            "chapters" -> books.sortedByDescending { it.chapters }
            "size" -> books.sortedByDescending { it.sizeBytes }
            else -> books.sortedByDescending { it.lastModified }
        }
    }

    private fun humanizeOperation(type: String): String = when (type) {
        "download" -> "Download"
        "update" -> "Update"
        "force_download" -> "Force download"
        "metadata" -> "Metadata"
        else -> type.replaceFirstChar { it.uppercase() }
    }

    private fun showSortDialog() {
        val options = arrayOf("Recent", "Title", "Author", "Chapters", "Size")
        val currentSort = viewModel.getCurrentSort()
        val checked = when (currentSort) {
            "title" -> 1
            "author" -> 2
            "chapters" -> 3
            "size" -> 4
            else -> 0
        }
        AlertDialog.Builder(this)
            .setTitle("Sort By")
            .setSingleChoiceItems(options, checked) { _, which ->
                val sort = when (which) {
                    1 -> "title"
                    2 -> "author"
                    3 -> "chapters"
                    4 -> "size"
                    else -> "modified"
                }
                viewModel.setSort(sort)
                syncBooks(viewModel.getBooksSnapshot())
            }
            .setPositiveButton("Close") { dialog, _ -> dialog.dismiss() }
            .show()
    }

    private fun showSearchDialog() {
        val input = EditText(this)
        input.hint = "Search title or author"
        input.setText(viewModel.searchQuery.value.orEmpty())
        AlertDialog.Builder(this)
            .setTitle("Search")
            .setView(input)
            .setPositiveButton("Search") { _, _ ->
                val query = input.text.toString().trim()
                viewModel.setSearchQuery(query.ifBlank { null })
                syncBooks(viewModel.getVisibleBooks())
            }
            .setNegativeButton("Clear") { _, _ ->
                viewModel.setSearchQuery(null)
                syncBooks(viewModel.getVisibleBooks())
            }
            .show()
    }

    private fun refreshAllBooks() {
        if (viewModel.hasRunningJob()) {
            toast("Download in progress, try again later")
            return
        }
        val updatable = viewModel.getBooksSnapshot().filter { it.url.isNotBlank() }
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
                viewModel.saveLibrary()
            }
        }.start()
    }
}
