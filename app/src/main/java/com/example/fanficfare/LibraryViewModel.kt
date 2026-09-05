package com.example.fanficfare

import androidx.lifecycle.LiveData
import androidx.lifecycle.MediatorLiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.fanficfare.data.local.DownloadJobEntity
import com.example.fanficfare.model.BookItem
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

    init {
        repository.getSavedSort()?.let { _currentSort.value = it }
        android.util.Log.d("FFF-UI-OBS", "LibraryViewModel init observer")
        _uiJobState.addSource(repository.latestJobs) { jobs ->
            android.util.Log.d("FFF-UI-OBS", "latestJobs fired count=${jobs.size}")
            val latest = jobs.maxWith(compareBy<DownloadJobEntity> { it.finishedAt ?: it.createdAt }.thenBy { it.id })
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
            val sort = _currentSort.value ?: "modified"
            val sorted = when (sort) {
                "title" -> books.sortedBy { it.title.lowercase() }
                "author" -> books.sortedBy { it.author.lowercase() }
                "chapters" -> books.sortedByDescending { it.chapters }
                "size" -> books.sortedByDescending { it.sizeBytes }
                else -> books.sortedByDescending { it.lastModified }
            }
            _visibleBooks.value = sorted
        }
    }

    private var _lastNotifiedTerminalJobId: Long? = null
    private val _observedNonTerminalJobIds = mutableSetOf<Long>()

    fun getCurrentSort(): String = _currentSort.value ?: "modified"

    fun setSort(sort: String) {
        _currentSort.value = sort
        repository.setSavedSort(sort)
        val current = repository.getBooks().toList()
        val sorted = when (sort) {
            "title" -> current.sortedBy { it.title.lowercase() }
            "author" -> current.sortedBy { it.author.lowercase() }
            "chapters" -> current.sortedByDescending { it.chapters }
            "size" -> current.sortedByDescending { it.sizeBytes }
            else -> current.sortedByDescending { it.lastModified }
        }
        repository.setBooks(sorted)
        recomputeVisible(sorted)
    }

    fun setSearchQuery(query: String?) {
        _searchQuery.value = query
        recomputeVisible()
    }

    fun recomputeVisible(books: List<BookItem> = repository.getBooks().toList()) {
        val q = _searchQuery.value
        val source = if (q.isNullOrBlank()) books else {
            val query = q.trim().lowercase()
            books.filter { it.title.lowercase().contains(query) || it.author.lowercase().contains(query) }
        }
        _visibleBooks.value = source
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
