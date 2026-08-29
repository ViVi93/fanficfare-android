package com.example.fanficfare

import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.LiveData
import androidx.lifecycle.MediatorLiveData
import androidx.lifecycle.MutableLiveData
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import androidx.work.BackoffPolicy
import java.util.concurrent.TimeUnit
import com.example.fanficfare.data.local.AppDatabase
import com.example.fanficfare.data.local.BookDao
import com.example.fanficfare.data.local.BookEntity
import com.example.fanficfare.data.local.DownloadJobDao
import com.example.fanficfare.data.local.DownloadJobEntity
import com.example.fanficfare.model.BookItem
import com.example.fanficfare.data.local.toBookItem
import com.example.fanficfare.data.local.toEntity
import com.example.fanficfare.FanFicFareWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class BookRepository(private val context: Context) {

    private val database = AppDatabase.getInstance(context)
    private val bookDao = database.bookDao()
    private val downloadJobDao = database.downloadJobDao()
    private val scope = CoroutineScope(Dispatchers.IO)
    private val prefs: SharedPreferences = context.getSharedPreferences("fanficfare_prefs", Context.MODE_PRIVATE)

    companion object {
        private const val KEY_SORT = "sort"
    }

    private val _books = MutableLiveData<List<BookItem>>(emptyList())
    val books: LiveData<List<BookItem>> = _books
    private val _latestJobs: MediatorLiveData<List<DownloadJobEntity>> = MediatorLiveData<List<DownloadJobEntity>>().apply {
        addSource(downloadJobDao.observeAll()) { value = it }
    }
    val latestJobs: LiveData<List<DownloadJobEntity>> = _latestJobs

    init {
        scope.launch {
            migrateIfNeeded()
            reconcileStaleRunningJobs()
            val initialEntities = bookDao.getAll()
            _books.postValue(initialEntities.map { it.toBookItem() })
            withContext(kotlinx.coroutines.Dispatchers.Main) {
                bookDao.observeAll().observeForever { entities ->
                    _books.postValue(entities.map { it.toBookItem() })
                }
            }
        }
    }

    private suspend fun reconcileStaleRunningJobs() = withContext(Dispatchers.IO) {
        try {
            val workManager = WorkManager.getInstance(context)
            val stale = downloadJobDao.getByStatus("running") + downloadJobDao.getByStatus("queued")
            for (job in stale) {
                val workId = job.workId?.ifBlank { null } ?: continue
                try {
                    val future = workManager.getWorkInfoById(java.util.UUID.fromString(workId))
                    val info = future.get()
                    when (info?.state) {
                        androidx.work.WorkInfo.State.SUCCEEDED -> {
                            val outputPath = job.outputPath?.ifBlank { null }
                            val file = outputPath?.let { java.io.File(it) }
                            val valid = file != null && file.exists() && file.isFile && file.length() > 0
                            if (valid) {
                                downloadJobDao.update(job.copy(status = "success", finishedAt = System.currentTimeMillis()))
                            } else {
                                downloadJobDao.update(job.copy(status = "failed", error = "stale_recovery_missing_output", finishedAt = System.currentTimeMillis()))
                            }
                        }
                        androidx.work.WorkInfo.State.FAILED -> {
                            downloadJobDao.update(job.copy(status = "failed", error = "workmanager_failed", finishedAt = System.currentTimeMillis()))
                        }
                        androidx.work.WorkInfo.State.CANCELLED -> {
                            downloadJobDao.update(job.copy(status = "cancelled", finishedAt = System.currentTimeMillis()))
                        }
                        else -> {}
                    }
                } catch (e: Exception) {
                    val outputPath = job.outputPath?.ifBlank { null }
                    val file = outputPath?.let { java.io.File(it) }
                    val valid = file != null && file.exists() && file.isFile && file.length() > 0
                    if (valid) {
                        downloadJobDao.update(job.copy(status = "success", finishedAt = System.currentTimeMillis()))
                    } else {
                        downloadJobDao.update(job.copy(status = "failed", error = "stale_recovery_work_missing", finishedAt = System.currentTimeMillis()))
                    }
                }
            }
        } catch (e: Exception) {
            // ignore reconciliation failures
        }
    }

    fun getBooks(): List<BookItem> = _books.value ?: emptyList()

    fun getBooksSnapshot(): List<BookItem> = (_books.value ?: emptyList()).toList()

    fun findByIdentity(book: BookItem): Int {
        val list = _books.value ?: return -1
        val byUrl = list.indexOfFirst { it.url.isNotBlank() && it.url == book.url }
        if (byUrl >= 0) return byUrl
        val normalized = book.uriString.trim()
        if (normalized.isNotBlank()) {
            return list.indexOfFirst { it.uriString.trim() == normalized }
        }
        return -1
    }

    fun addOrUpdate(book: BookItem) {
        val list = (_books.value ?: emptyList()).toMutableList()
        val idx = findByIdentity(book)
        val msg = "title=${book.title} url=${book.url} path=${book.uriString} idx=$idx sizeBefore=${list.size}"
        android.util.Log.d("FFF-Dup", msg)
        DiagnosticLog.append(context, "FFF-Dup", msg)
        if (idx >= 0) {
            list[idx] = book
            val msg2 = "addOrUpdate replaced_at=$idx"
            android.util.Log.d("FFF-Dup", msg2)
            DiagnosticLog.append(context, "FFF-Dup", msg2)
        } else {
            list.add(0, book)
            val msg2 = "addOrUpdate appended"
            android.util.Log.d("FFF-Dup", msg2)
            DiagnosticLog.append(context, "FFF-Dup", msg2)
        }
        _books.value = list
        val msg3 = "addOrUpdate sizeAfter=${list.size}"
        android.util.Log.d("FFF-Dup", msg3)
        DiagnosticLog.append(context, "FFF-Dup", msg3)
        scope.launch {
            upsertBookEntity(book)
        }
    }

    fun updateBook(oldBook: BookItem, newBook: BookItem) {
        val list = (_books.value ?: emptyList()).toMutableList()
        val idx = findByIdentity(oldBook)
        if (idx >= 0) list[idx] = newBook else list.add(0, newBook)
        _books.value = list
        scope.launch {
            upsertBookEntity(newBook)
        }
    }

    fun remove(book: BookItem) {
        val list = (_books.value ?: emptyList()).toMutableList()
        val removed = list.remove(book)
        _books.value = list
        if (removed) {
            scope.launch {
                findByExisting(book)?.let { bookDao.delete(it) }
            }
        }
    }

    fun clear() {
        _books.value = emptyList()
        scope.launch {
            bookDao.clear()
        }
    }

    fun setBooks(newBooks: List<BookItem>) {
        val msg = "setBooks count=${newBooks.size}"
        android.util.Log.d("FFF-Dup", msg)
        DiagnosticLog.append(context, "FFF-Dup", msg)
        _books.value = newBooks.toList()
        scope.launch {
            bookDao.clear()
            bookDao.insertAll(newBooks.map { it.toEntity() })
        }
    }

    suspend fun loadLibrary(): Boolean {
        val entities = bookDao.getAll()
        val msg = "loadLibrary entityCount=${entities.size}"
        android.util.Log.d("FFF-Dup", msg)
        DiagnosticLog.append(context, "FFF-Dup", msg)
        _books.value = entities.map { it.toBookItem() }
        return true
    }

    suspend fun saveLibrary(): Boolean {
        val books = _books.value ?: return false
        withContext(Dispatchers.IO) {
            bookDao.clear()
            bookDao.insertAll(books.map { it.toEntity() })
        }
        return true
    }

    private suspend fun upsertBookEntity(book: BookItem) {
        withContext(Dispatchers.IO) {
            val existing = findByExisting(book)
            if (existing != null) {
                bookDao.update(book.toEntity(now = existing.addedAt))
            } else {
                bookDao.insert(book.toEntity())
            }
        }
    }

    private suspend fun findByExisting(book: BookItem): BookEntity? {
        return withContext(Dispatchers.IO) {
            val normalizedUrl = book.url.trim().ifBlank { null }
            val normalizedPath = book.uriString.trim()
            if (!normalizedUrl.isNullOrBlank()) {
                bookDao.findByUrl(normalizedUrl)?.let { return@withContext it }
            }
            if (normalizedPath.isNotBlank()) {
                bookDao.findByFilePath(normalizedPath)?.let { return@withContext it }
            }
            null
        }
    }

    private suspend fun migrateIfNeeded() {
        withContext(Dispatchers.IO) {
            if (prefs.getBoolean("library_migrated_v1", false)) {
                return@withContext
            }
            if (bookDao.getAll().isNotEmpty()) {
                prefs.edit().putBoolean("library_migrated_v1", true).apply()
                return@withContext
            }
            val indexPath = getFilePath("library_index.json")
            if (!java.io.File(indexPath).exists()) {
                prefs.edit().putBoolean("library_migrated_v1", true).apply()
                return@withContext
            }
            val text = try { java.io.File(indexPath).readText() } catch (e: Exception) { null }
            if (text.isNullOrBlank()) {
                prefs.edit().putBoolean("library_migrated_v1", true).apply()
                return@withContext
            }
            try {
                val result = JSONObject(text)
                val booksArray = result.optJSONArray("books") ?: JSONArray()
                val entities = mutableListOf<BookEntity>()
                for (i in 0 until booksArray.length()) {
                    val b = booksArray.getJSONObject(i)
                    val now = System.currentTimeMillis()
                    entities += BookEntity(
                        title = b.optString("title", "untitled"),
                        author = b.optString("author", ""),
                        url = b.optString("url", "").trim().ifBlank { null },
                        filePath = b.optString("path", "").trim(),
                        sourcePath = b.optString("source", "").trim().ifBlank { null },
                        lastModified = b.optLong("modified", 0L),
                        sizeBytes = b.optLong("size", 0L),
                        coverData = b.optString("cover", "").ifBlank { null },
                        chapters = b.optInt("chapters", 0),
                        addedAt = now
                    )
                }
                bookDao.insertAll(entities)
                prefs.edit().putBoolean("library_migrated_v1", true).apply()
            } catch (e: Exception) {
                // corrupt JSON: do not mark migrated; leave JSON intact
            }
        }
    }

    private fun getFilePath(name: String): String {
        val dir = context.filesDir
        if (!dir.exists()) dir.mkdirs()
        return java.io.File(dir, name).absolutePath
    }

    fun getSavedSort(): String? = prefs.getString(KEY_SORT, null)

    fun setSavedSort(sort: String) {
        prefs.edit().putString(KEY_SORT, sort).apply()
    }

    suspend fun enqueueDownload(url: String): Long {
        val job = DownloadJobEntity(
            bookId = 0,
            type = "download",
            status = "queued",
            inputUrl = url,
            createdAt = System.currentTimeMillis()
        )
        val jobId = downloadJobDao.insert(job)
        val requestWorkId = java.util.UUID.randomUUID().toString()
        val work = OneTimeWorkRequestBuilder<FanFicFareWorker>()
            .setInputData(
                workDataOf(
                    FanFicFareWorker.KEY_TYPE to "download",
                    FanFicFareWorker.KEY_URL to url,
                    FanFicFareWorker.KEY_WORK_ID to requestWorkId
                )
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            requestWorkId,
            ExistingWorkPolicy.KEEP,
            work
        )
        downloadJobDao.update(job.copy(id = jobId, workId = work.id.toString()))
        return jobId
    }

    suspend fun enqueueUpdate(bookId: Long, inputPath: String): Long {
        val job = DownloadJobEntity(
            bookId = bookId,
            type = "update",
            status = "queued",
            inputPath = inputPath,
            createdAt = System.currentTimeMillis()
        )
        val jobId = downloadJobDao.insert(job)
        val requestWorkId = java.util.UUID.randomUUID().toString()
        val work = OneTimeWorkRequestBuilder<FanFicFareWorker>()
            .setInputData(
                workDataOf(
                    FanFicFareWorker.KEY_TYPE to "update",
                    FanFicFareWorker.KEY_BOOK_ID to bookId,
                    FanFicFareWorker.KEY_INPUT_PATH to inputPath,
                    FanFicFareWorker.KEY_WORK_ID to requestWorkId
                )
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            FanFicFareWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            work
        )
        downloadJobDao.update(job.copy(id = jobId, workId = work.id.toString()))
        return jobId
    }

    suspend fun enqueueForceDownload(bookId: Long, inputPath: String): Long {
        val job = DownloadJobEntity(
            bookId = bookId,
            type = "force_download",
            status = "queued",
            inputPath = inputPath,
            createdAt = System.currentTimeMillis()
        )
        val jobId = downloadJobDao.insert(job)
        val requestWorkId = java.util.UUID.randomUUID().toString()
        val work = OneTimeWorkRequestBuilder<FanFicFareWorker>()
            .setInputData(
                workDataOf(
                    FanFicFareWorker.KEY_TYPE to "force_download",
                    FanFicFareWorker.KEY_BOOK_ID to bookId,
                    FanFicFareWorker.KEY_INPUT_PATH to inputPath,
                    FanFicFareWorker.KEY_WORK_ID to requestWorkId
                )
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            FanFicFareWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            work
        )
        downloadJobDao.update(job.copy(id = jobId, workId = work.id.toString()))
        return jobId
    }

    suspend fun enqueueMetadata(url: String): Long {
        val job = DownloadJobEntity(
            bookId = 0,
            type = "metadata",
            status = "queued",
            inputUrl = url,
            createdAt = System.currentTimeMillis()
        )
        val jobId = downloadJobDao.insert(job)
        val requestWorkId = java.util.UUID.randomUUID().toString()
        val work = OneTimeWorkRequestBuilder<FanFicFareWorker>()
            .setInputData(
                workDataOf(
                    FanFicFareWorker.KEY_TYPE to "metadata",
                    FanFicFareWorker.KEY_URL to url,
                    FanFicFareWorker.KEY_WORK_ID to requestWorkId
                )
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            FanFicFareWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            work
        )
        downloadJobDao.update(job.copy(id = jobId, workId = work.id.toString()))
        return jobId
    }

    suspend fun getJob(jobId: Long): DownloadJobEntity? = downloadJobDao.getById(jobId)

    fun cancelCurrentDownload() {
        DiagnosticLog.append(context, "Main.Cancel", "cancel_start")
        try {
            WorkManager.getInstance(context).cancelUniqueWork(FanFicFareWorker.UNIQUE_WORK_NAME)
            DiagnosticLog.append(context, "Main.Cancel", "workmanager_cancelled")
        } catch (e: Exception) {
            DiagnosticLog.appendException(context, "Main.Cancel", "workmanager_cancel_failed", e)
            android.util.Log.e("FFF-Cancel", "cancel failed", e)
        }
        scope.launch(Dispatchers.IO) {
            try {
                val dao = database.downloadJobDao()
                val stale = dao.getByStatus("running") + dao.getByStatus("queued")
                val cancelled = stale.map { it.copy(status = "cancelled", finishedAt = System.currentTimeMillis()) }
                cancelled.forEach { dao.update(it) }
                DiagnosticLog.append(context, "Main.Cancel", "db_updated count=${cancelled.size}")
            } catch (e: Exception) {
                DiagnosticLog.appendException(context, "Main.Cancel", "db_update_failed", e)
            }
        }
    }

    fun retryJob(job: DownloadJobEntity) {
        when (job.type) {
            "download" -> { job.inputUrl?.let { scope.launch { enqueueDownload(it) } } }
            "update" -> { job.inputPath?.let { scope.launch { enqueueUpdate(job.bookId, it) } } }
            "force_download" -> { job.inputPath?.let { scope.launch { enqueueForceDownload(job.bookId, it) } } }
            "metadata" -> { job.inputUrl?.let { scope.launch { enqueueMetadata(it) } } }
        }
    }

    fun hasRunningJob(): Boolean {
        val jobs = _latestJobs.value ?: return false
        return jobs.any { it.status == "running" || it.status == "queued" }
    }
}
