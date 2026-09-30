package com.vivi.aharana

import androidx.lifecycle.LiveData
import androidx.lifecycle.MediatorLiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vivi.aharana.data.local.DownloadJobEntity
import com.vivi.aharana.model.BookItem
import kotlinx.coroutines.launch

class JobUiState(
    val jobId: Long = 0,
    val type: String = "",
    val status: String = "",
    val phase: String = "",
    val indeterminate: Boolean = true,
    val finished: Boolean = false
)

class LibraryViewModel(private val repository: BookRepository) : ViewModel() {

    val books: LiveData<List<BookItem>> = repository.books
    val latestJobs: LiveData<List<DownloadJobEntity>> = repository.latestJobs
    private val _uiJobState = MediatorLiveData<JobUiState?>(null)
    val uiJobState: LiveData<JobUiState?> = _uiJobState
    private val _currentSort = MutableLiveData<String>("modified")
    val currentSort: LiveData<String> = _currentSort
    private val _searchQuery = MutableLiveData<String?>(null)
    val searchQuery: LiveData<String?> = _searchQuery
    private val _visibleBooks = MutableLiveData<List<BookItem>>(emptyList())
    val visibleBooks: LiveData<List<BookItem>> = _visibleBooks

    // Declared BEFORE init on purpose: Kotlin runs property initializers and
    // init blocks in declaration order, so anything declared after init is
    // still null when init runs. The init block below restores the saved sort
    // direction, so this state must already exist by then.
    private var _sortDirection = true
    private val _sortDirectionLive = MutableLiveData<Boolean>(true)
    val sortDirection: LiveData<Boolean> = _sortDirectionLive

    init {
        repository.getSavedSort()?.let { _currentSort.value = it }
        _sortDirection = repository.getSavedSortDirection()
        _sortDirectionLive.value = _sortDirection
        android.util.Log.d("FFF-UI-OBS", "LibraryViewModel init observer")
        _uiJobState.addSource(repository.latestJobs) { jobs ->
            android.util.Log.d("FFF-UI-OBS", "latestJobs fired count=${jobs.size}")
            val latest = jobs.maxWithOrNull(compareBy<DownloadJobEntity> { it.finishedAt ?: it.createdAt }.thenBy { it.id })
            android.util.Log.d("FFF-UI-OBS", "selected job=${latest?.id} status=${latest?.status} finished=${latest?.status in setOf("success","failed","cancelled")}")
            android.util.Log.d("FFF-UI", "selected job=${latest?.id} status=${latest?.status} finished=${latest?.status in setOf("success","failed","cancelled")}")
            val terminal = latest?.status?.let { it == "success" || it == "failed" || it == "cancelled" } ?: false
            if (latest == null) {
                _lastNotifiedTerminalJobId = null
                _uiJobState.value = null
                return@addSource
            }
            if (terminal) {
                _lastNotifiedTerminalJobId = latest.id
                _uiJobState.value = JobUiState(
                    jobId = latest.id,
                    type = latest.type,
                    status = latest.status,
                    phase = humanizeJobStatus(latest.status),
                    indeterminate = false,
                    finished = true
                )
                _observedNonTerminalJobIds.remove(latest.id)
            } else {
                _lastNotifiedTerminalJobId = null
                _observedNonTerminalJobIds.add(latest.id)
                _uiJobState.value = JobUiState(
                    jobId = latest.id,
                    type = latest.type,
                    status = latest.status,
                    phase = humanizeJobStatus(latest.status),
                    indeterminate = true,
                    finished = false
                )
            }
        }
        repository.books.observeForever { books ->
            _visibleBooks.value = sorted(books)
        }
    }

    private var _lastNotifiedTerminalJobId: Long? = null
    private val _observedNonTerminalJobIds = mutableSetOf<Long>()

    fun getCurrentSort(): String = _currentSort.value ?: "modified"

    fun setSort(sort: String) {
        _currentSort.value = sort
        repository.setSavedSort(sort)
        repository.setSavedSortDirection(_sortDirection)
        val sorted = sorted(repository.getBooks().toList())
        repository.setBooks(sorted)
        recomputeVisible(sorted)
    }

    fun setSearchQuery(query: String?) {
        _searchQuery.value = query
        recomputeVisible()
    }

    fun setSortDirection(descending: Boolean) {
        _sortDirection = descending
        _sortDirectionLive.value = descending
        // Persist here as well as in setSort(): flipping the direction is its own
        // change, and without this it only survived until the process died — the
        // next launch restored whatever setSort() last wrote, or the default.
        repository.setSavedSortDirection(descending)
        val current = repository.getBooks().toList()
        recomputeVisible(current)
    }

    fun flipSortDirection() {
        setSortDirection(!_sortDirection)
    }

    fun isSortDirectionDescending(): Boolean = _sortDirection

    private fun sorted(books: List<BookItem>): List<BookItem> {
        val sort = _currentSort.value ?: "modified"
        return when (sort) {
            "title" -> if (_sortDirection) books.sortedByDescending { it.title.lowercase() } else books.sortedBy { it.title.lowercase() }
            "author" -> if (_sortDirection) books.sortedByDescending { it.author.lowercase() } else books.sortedBy { it.author.lowercase() }
            "chapters" -> if (_sortDirection) books.sortedByDescending { it.chapters } else books.sortedBy { it.chapters }
            "size" -> if (_sortDirection) books.sortedByDescending { it.sizeBytes } else books.sortedBy { it.sizeBytes }
            else -> if (_sortDirection) books.sortedByDescending { it.lastModified } else books.sortedBy { it.lastModified }
        }
    }

    fun recomputeVisible(books: List<BookItem> = repository.getBooks().toList()) {
        val q = _searchQuery.value
        val source = if (q.isNullOrBlank()) books else {
            val query = q.trim().lowercase()
            books.filter { it.title.lowercase().contains(query) || it.author.lowercase().contains(query) }
        }
        _visibleBooks.value = sorted(source)
    }

    fun loadLibrary(): Boolean {
        var ok = false
        viewModelScope.launch {
            ok = repository.loadLibrary()
            if (ok) {
                val sort = _currentSort.value ?: "modified"
                setSort(sort)
            }
        }
        return ok
    }

    /**
     * Re-read the store and re-sort. Must run on the main thread: it assigns
     * LiveData (repository.loadLibrary and setSort both setValue).
     *
     * Used after a worker has written a new book, so the caller sees it without
     * inserting a second copy itself.
     */
    suspend fun reloadFromStore(): Boolean {
        val ok = repository.loadLibrary()
        if (ok) {
            setSort(_currentSort.value ?: "modified")
        }
        return ok
    }

    fun saveLibrary(): Boolean {
        var ok = false
        viewModelScope.launch {
            ok = repository.saveLibrary()
        }
        return ok
    }

    fun addOrUpdate(book: BookItem) {
        repository.addOrUpdate(book)
        recomputeVisible()
    }

    fun updateBook(oldBook: BookItem, newBook: BookItem) {
        repository.updateBook(oldBook, newBook)
        recomputeVisible()
    }

    fun remove(book: BookItem) {
        repository.remove(book)
        recomputeVisible()
    }

    fun deleteBook(book: BookItem) {
        viewModelScope.launch {
            repository.remove(book)
        }
    }

    fun clearLibrary() {
        repository.clear()
        recomputeVisible()
    }

    private val _selectionMode = MutableLiveData<Boolean?>(null)
    val selectionMode: LiveData<Boolean?> = _selectionMode

    fun setSelectionMode(mode: Boolean) {
        _selectionMode.value = mode
    }

    fun isInSelectionMode(): Boolean = _selectionMode.value == true

    fun clearSelectionState() {
        _selectionMode.value = null
    }

    fun findByIdentity(book: BookItem): Int = repository.findByIdentity(book)

    private fun humanizeJobStatus(status: String): String = when (status) {
        "queued" -> "Queued"
        "running" -> "Running"
        "success" -> "Complete"
        "failed" -> "Failed"
        "cancelled" -> "Cancelled"
        else -> status.replaceFirstChar { it.uppercase() }
    }

    fun getBooksSnapshot(): List<BookItem> = repository.getBooksSnapshot()
    fun getVisibleBooks(): List<BookItem> = _visibleBooks.value.orEmpty().toList()
    fun setBooks(newBooks: List<BookItem>) {
        repository.setBooks(newBooks)
        recomputeVisible(newBooks)
    }

    fun hasRunningJob(): Boolean = repository.hasRunningJob()

    fun cancelCurrentDownload() {
        repository.cancelCurrentDownload()
    }

    fun enqueueDownload(url: String) = viewModelScope.launch { repository.enqueueDownload(url) }
    fun enqueueUpdate(bookId: Long, inputPath: String) = viewModelScope.launch { repository.enqueueUpdate(bookId, inputPath) }
    fun enqueueForceDownload(bookId: Long, inputPath: String) = viewModelScope.launch { repository.enqueueForceDownload(bookId, inputPath) }
    suspend fun enqueueMetadata(url: String): Long = repository.enqueueMetadata(url)
}
