package com.example.fanficfare

import android.app.NotificationChannel
import android.content.Context
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.example.fanficfare.data.local.AppDatabase
import com.example.fanficfare.data.local.BookDao
import com.example.fanficfare.data.local.BookEntity
import com.example.fanficfare.data.local.DownloadJobDao
import com.example.fanficfare.data.local.DownloadJobEntity
import com.example.fanficfare.data.local.toEntity
import com.example.fanficfare.model.BookItem
import org.json.JSONObject
import java.io.File

class FanFicFareWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        const val CHANNEL_ID = "fanficfare_worker_channel"
        const val NOTIFICATION_ID = 1
        const val KEY_TYPE = "type"
        const val KEY_URL = "url"
        const val KEY_INPUT_PATH = "inputPath"
        const val KEY_BOOK_ID = "bookId"
        const val KEY_WORK_ID = "workId"
        const val TYPE_DOWNLOAD = "download"
        const val TYPE_UPDATE = "update"
        const val TYPE_FORCE_DOWNLOAD = "force_download"
        const val TYPE_METADATA = "metadata"
        const val UNIQUE_WORK_NAME = "fanficfare_unique_work"
        const val PROGRESS_STATUS = "status"
        const val PROGRESS_PHASE = "phase"
        const val PROGRESS_INDETERMINATE = "indeterminate"
    }

    init {
        createNotificationChannel()
    }

    private suspend fun setPhase(status: String, indeterminate: Boolean = true) {
        setProgress(
            Data.Builder()
                .putString(PROGRESS_STATUS, status)
                .putString(PROGRESS_PHASE, humanize(status))
                .putBoolean(PROGRESS_INDETERMINATE, indeterminate)
                .build()
        )
    }

    private suspend fun updateJobStatus(jobDao: DownloadJobDao, job: DownloadJobEntity, status: String) {
        jobDao.update(job.copy(status = status))
        logWorker("doWork", "db_status jobId=${job.id} status=$status")
    }

    private fun humanize(status: String): String = when (status) {
        "queued" -> "Queued"
        "preparing" -> "Preparing"
        "downloading" -> "Downloading"
        "processing" -> "Processing"
        "copying" -> "Copying"
        "completed" -> "Complete"
        "failed" -> "Failed"
        "cancelled" -> "Cancelled"
        "fetching_metadata" -> "Fetching metadata"
        else -> status.replaceFirstChar { it.uppercase() }
    }

    private fun logWorker(tag: String, message: String) {
        val text = "[$tag] $message"
        android.util.Log.d("FFF-Worker", text)
        try {
            DiagnosticLog.append(applicationContext, "FFF-Worker", text)
        } catch (e: Exception) {
            android.util.Log.e("FFF-Worker", "log_failed", e)
        }
    }

    private suspend fun upsertBook(
        bookDao: BookDao,
        candidate: BookEntity,
        filePath: String
    ): BookEntity {
        val existing = if (!candidate.url.isNullOrBlank()) {
            bookDao.findByUrl(candidate.url) ?: bookDao.findByFilePath(filePath)
        } else {
            bookDao.findByFilePath(filePath)
        }
        return if (existing != null) {
            val merged = candidate.copy(
                id = existing.id,
                addedAt = existing.addedAt
            )
            bookDao.update(merged)
            android.util.Log.d("FFF-Dup", "upsertBook updated id=${merged.id}")
            merged
        } else {
            val newId = bookDao.insert(candidate)
            android.util.Log.d("FFF-Dup", "upsertBook inserted id=$newId")
            candidate.copy(id = newId)
        }
    }

    override suspend fun getForegroundInfo(): ForegroundInfo {
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("FanFicFare")
            .setContentText("Running ${inputData.getString(KEY_TYPE) ?: "task"}")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .build()
        return ForegroundInfo(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    }

    override suspend fun doWork(): Result {
        logWorker("doWork", "ENTER url=${inputData.getString(KEY_URL)} type=${inputData.getString(KEY_TYPE)} workId=${inputData.getString(KEY_WORK_ID)}")
        val type = inputData.getString(KEY_TYPE) ?: return Result.failure().also { logWorker("doWork", "no_type") }
        val url = inputData.getString(KEY_URL) ?: ""
        val inputPath = inputData.getString(KEY_INPUT_PATH) ?: ""
        val bookId = inputData.getLong(KEY_BOOK_ID, -1L)
        val workId = inputData.getString(KEY_WORK_ID) ?: ""
        logWorker("doWork", "start type=$type url=$url workId=$workId")

        if (isStopped) {
            logWorker("doWork", "stopped_early")
            return Result.failure()
        }

        setForeground(getForegroundInfo())

        if (isStopped) {
            logWorker("doWork", "stopped_early")
            return Result.failure()
        }

        val database = AppDatabase.getInstance(applicationContext)
        val bookDao = database.bookDao()
        val jobDao = database.downloadJobDao()

        val existingJob = if (workId.isNotBlank()) jobDao.findByWorkId(workId) else null
        val recovery = when {
            existingJob == null -> null.also { logWorker("doWork", "no_existing_job") }
            existingJob.status == "success" -> recoverExistingSuccess(type, existingJob, bookDao, jobDao).also { logWorker("doWork", "recovered_success") }
            existingJob.status == "cancelled" -> Result.failure().also { logWorker("doWork", "existing_cancelled") }
            else -> null.also { logWorker("doWork", "existing_status=${existingJob.status}") }
        }
        if (recovery != null) return recovery

        val job = DownloadJobEntity(
            bookId = bookId,
            type = type,
            status = "running",
            inputUrl = url.ifBlank { null },
            inputPath = inputPath.ifBlank { null },
            createdAt = System.currentTimeMillis()
        )
        val jobId = jobDao.insert(job)
        logWorker("doWork", "job_inserted id=$jobId")

        return try {
            if (isStopped) {
                jobDao.update(
                    job.copy(
                        id = jobId,
                        status = "cancelled",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                logWorker("doWork", "stopped_before_phase")
                return Result.failure()
            }

            setPhase("preparing")
            logWorker("doWork", "phase=preparing")

            when (type) {
                TYPE_DOWNLOAD -> {
                    logWorker("doWork", "calling_handleDownload")
                    handleDownload(url, bookDao, jobDao, job.copy(id = jobId)).also { logWorker("doWork", "handleDownload_result=$it") }
                }
                TYPE_UPDATE -> {
                    logWorker("doWork", "calling_handleUpdate")
                    handleUpdate(bookId, inputPath, bookDao, jobDao, job.copy(id = jobId)).also { logWorker("doWork", "handleUpdate_result=$it") }
                }
                TYPE_FORCE_DOWNLOAD -> {
                    logWorker("doWork", "calling_handleForceDownload")
                    handleForceDownload(bookId, inputPath, bookDao, jobDao, job.copy(id = jobId)).also { logWorker("doWork", "handleForceDownload_result=$it") }
                }
                TYPE_METADATA -> {
                    logWorker("doWork", "calling_handleMetadata")
                    handleMetadata(url, jobDao, job.copy(id = jobId)).also { logWorker("doWork", "handleMetadata_result=$it") }
                }
                else -> {
                    jobDao.update(
                        job.copy(
                            id = jobId,
                            status = "failed",
                            error = "Unknown type: $type",
                            finishedAt = System.currentTimeMillis()
                        )
                    )
                    logWorker("doWork", "unknown_type")
                    setPhase("failed")
                    Result.failure()
                }
            }
        } catch (e: Exception) {
            logWorker("doWork", "exception=${e.javaClass.simpleName}: ${e.message ?: "null"}")
            jobDao.update(
                job.copy(
                    id = jobId,
                    status = "failed",
                    error = e.message,
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            Result.failure()
        }.also { result ->
            logWorker("doWork", "final_result=$result")
        }
    }

    private suspend fun recoverExistingSuccess(
        type: String,
        existingJob: DownloadJobEntity,
        bookDao: BookDao,
        jobDao: DownloadJobDao
    ): Result {
        if (isStopped) {
            return Result.failure()
        }
        when (type) {
            TYPE_METADATA -> return Result.success()
        }
        val outputPath = existingJob.outputPath?.ifBlank { null } ?: return Result.failure()
        val file = File(outputPath)
        val valid = file.exists() && file.isFile && file.length() > 0
        if (!valid) return Result.failure()
        if (isStopped) {
            return Result.failure()
        }
        return when (type) {
            TYPE_DOWNLOAD, TYPE_FORCE_DOWNLOAD -> {
                val existing = existingJob.bookId.takeIf { it > 0 }?.let { bookDao.findById(it) }
                val current = jobDao.getById(existingJob.id)
                if (current?.status == "cancelled") return Result.failure()
                if (existing == null) {
                    val book = BookItem(
                        title = File(outputPath).nameWithoutExtension,
                        author = "",
                        uriString = outputPath,
                        lastModified = System.currentTimeMillis(),
                        sizeBytes = file.length(),
                        coverUriString = null,
                        url = existingJob.inputUrl ?: "",
                        chapters = 0,
                        sourceUriString = outputPath
                    ).toEntity()
                    val before = bookDao.findByFilePath(outputPath)
                    android.util.Log.d("FFF-Dup", "recoverDownload title=${book.title} path=${outputPath} before=${before?.id}")
                    val saved = upsertBook(bookDao, book, outputPath)
                    android.util.Log.d("FFF-Dup", "recoverDownload inserted id=${saved.id}")
                    jobDao.update(
                        existingJob.copy(
                            bookId = saved.id,
                            status = "success",
                            finishedAt = System.currentTimeMillis()
                        )
                    )
                } else {
                    jobDao.update(
                        existingJob.copy(
                            status = "success",
                            finishedAt = System.currentTimeMillis()
                        )
                    )
                }
                setPhase("completed", indeterminate = false)
                Result.success()
            }
            TYPE_UPDATE -> {
                val existing = existingJob.bookId.takeIf { it > 0 }?.let { bookDao.findById(it) }
                val current = jobDao.getById(existingJob.id)
                if (current?.status == "cancelled") return Result.failure()
                if (existing != null) {
                    val before = bookDao.findByFilePath(outputPath)
                    android.util.Log.d("FFF-Dup", "recoverUpdate title=${existing.title} path=${outputPath} existingId=${existing.id} before=${before?.id}")
                    val saved = upsertBook(bookDao, existing.copy(filePath = outputPath, lastModified = System.currentTimeMillis(), sizeBytes = file.length()), outputPath)
                    android.util.Log.d("FFF-Dup", "recoverUpdate updated id=${saved.id}")
                }
                jobDao.update(
                    existingJob.copy(
                        status = "success",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                setPhase("completed", indeterminate = false)
                Result.success()
            }
            else -> Result.failure()
        }
    }

    private suspend fun handleDownload(
        url: String,
        bookDao: BookDao,
        jobDao: DownloadJobDao,
        job: DownloadJobEntity
    ): Result {
        if (url.isBlank()) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "Missing URL",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        setPhase("downloading")

        val bridge = PythonBridge(applicationContext)
        val outputDir = applicationContext.filesDir.absolutePath
        logWorker("handleDownload", "bridge_call url=$url outputDir=$outputDir")
        val raw = bridge.fanficfareDownload(url, outputDir)
        logWorker("handleDownload", "bridge_raw_len=${raw.length}")
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        val result = JSONObject(raw)
        logWorker("handleDownload", "result_json_ok=${result.optBoolean("ok")} title=${result.optString("title", "")}")
        if (!result.optBoolean("ok")) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = result.optString("error", "unknown"),
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val title = result.optString("title", "story")
        val internalPath = result.optString("path", "")
        logWorker("handleDownload", "result_path=$internalPath")
        if (internalPath.isBlank()) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "missing output path",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val source = File(internalPath)
        logWorker("handleDownload", "source_path=$internalPath exists=${source.exists()} isFile=${source.isFile} size=${source.length()}")
        if (!source.exists() || !source.isFile) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "generated file missing",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        setPhase("processing")

        val savedOutputDir = SettingsActivity.getOutputDir(applicationContext)
        logWorker("handleDownload", "output_dir=$savedOutputDir")
        val finalPath = try {
            val copied = StorageBridge.copyToOutputDir(applicationContext, source, savedOutputDir)
            logWorker("handleDownload", "copied_to=$copied")
            copied
        } catch (e: Exception) {
            logWorker("handleDownload", "copy_exception=${e.javaClass.simpleName}: ${e.message}")
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = e.message,
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        } finally {
            source.delete()
        }
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        setPhase("copying")

        val author = result.optString("author", "")
        val bookUrl = result.optString("url", url)
        val chapters = result.optInt("chapters", 0)
        val cover = result.optString("cover", "")
        val size = result.optLong("size", 0L)
        val modified = result.optLong("modified", System.currentTimeMillis())
        val current = jobDao.getById(job.id)
        if (current?.status == "cancelled") {
            setPhase("cancelled")
            return Result.failure()
        }
        val entity = BookItem(
            title = title,
            author = author,
            uriString = finalPath,
            lastModified = modified,
            sizeBytes = size,
            coverUriString = cover,
            url = bookUrl,
            chapters = chapters,
            sourceUriString = finalPath
        ).toEntity()

        val before = bookDao.findByFilePath(finalPath)
        android.util.Log.d("FFF-Dup", "handleDownload title=${entity.title} path=${finalPath} before=${before?.id}")
        val saved = upsertBook(bookDao, entity, finalPath)
        android.util.Log.d("FFF-Dup", "handleDownload inserted id=${saved.id}")
        logWorker("handleDownload", "upserted id=${saved.id} path=$finalPath")
        jobDao.update(
            job.copy(
                bookId = saved.id,
                status = "success",
                outputPath = finalPath,
                finishedAt = System.currentTimeMillis()
            )
        )
        setPhase("completed", indeterminate = false)
        return Result.success()
    }

    private suspend fun handleUpdate(
        bookId: Long,
        inputPath: String,
        bookDao: BookDao,
        jobDao: DownloadJobDao,
        job: DownloadJobEntity
    ): Result {
        val existing = if (bookId > 0) bookDao.findById(bookId) else null
        val path = inputPath.ifBlank { existing?.filePath } ?: return Result.failure()
        if (path.isBlank()) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "missing input path",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val bridge = PythonBridge(applicationContext)
        val outputDir = applicationContext.filesDir.absolutePath
        val localFile = StorageBridge.resolveLocalEpub(applicationContext, path)?.first ?: return Result.failure()
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        setPhase("downloading")
        val raw = bridge.updateEpubFromPath(localFile.absolutePath, outputDir)
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        val result = JSONObject(raw)
        if (!result.optBoolean("ok")) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = result.optString("error", "unknown"),
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val title = result.optString("title", existing?.title ?: "story")
        val internalPath = result.optString("path", "")
        if (internalPath.isNotBlank() && File(internalPath).exists()) {
            if (isStopped) {
                jobDao.update(
                    job.copy(
                        status = "cancelled",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                setPhase("cancelled")
                return Result.failure()
            }
            setPhase("processing")
            val savedOutputDir = SettingsActivity.getOutputDir(applicationContext)
            val finalPath = try {
                StorageBridge.copyToOutputDir(applicationContext, File(internalPath), savedOutputDir)
            } finally {
                File(internalPath).delete()
            }
            if (isStopped) {
                jobDao.update(
                    job.copy(
                        status = "cancelled",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                setPhase("cancelled")
                return Result.failure()
            }
            setPhase("copying")
            val updated = if (existing != null) {
                existing.copy(
                    id = existing.id,
                    title = title,
                    filePath = finalPath,
                    lastModified = result.optLong("modified", System.currentTimeMillis()),
                    sizeBytes = result.optLong("size", 0L),
                    coverData = result.optString("cover", existing.coverData ?: ""),
                    url = result.optString("url", existing.url ?: ""),
                    chapters = result.optInt("chapters", existing.chapters)
                )
            } else {
                BookItem(
                    title = title,
                    author = "",
                    uriString = finalPath,
                    lastModified = result.optLong("modified", System.currentTimeMillis()),
                    sizeBytes = result.optLong("size", 0L),
                    coverUriString = result.optString("cover", ""),
                    url = result.optString("url", ""),
                    chapters = result.optInt("chapters", 0),
                    sourceUriString = finalPath
                ).toEntity()
            }
            val current = jobDao.getById(job.id)
            if (current?.status == "cancelled") {
                setPhase("cancelled")
                return Result.failure()
            }
            val before = bookDao.findByFilePath(finalPath)
            android.util.Log.d("FFF-Dup", "handleUpdate title=${updated.title} path=${finalPath} existingId=${existing?.id} before=${before?.id}")
            val saved = upsertBook(bookDao, updated, finalPath)
            android.util.Log.d("FFF-Dup", "handleUpdate inserted id=${saved.id}")
            jobDao.update(
                job.copy(
                    bookId = saved.id,
                    status = "success",
                    outputPath = finalPath,
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("completed", indeterminate = false)
            return Result.success()
        }

        jobDao.update(
            job.copy(
                status = "success",
                finishedAt = System.currentTimeMillis()
            )
        )
        setPhase("completed", indeterminate = false)
        return Result.success()
    }

    private suspend fun handleForceDownload(
        bookId: Long,
        inputPath: String,
        bookDao: BookDao,
        jobDao: DownloadJobDao,
        job: DownloadJobEntity
    ): Result {
        val existing = if (bookId > 0) bookDao.findById(bookId) else null
        val path = inputPath.ifBlank { existing?.filePath } ?: return Result.failure()
        if (path.isBlank()) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "missing input path",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val bridge = PythonBridge(applicationContext)
        val outputDir = applicationContext.filesDir.absolutePath
        val localFile = StorageBridge.resolveLocalEpub(applicationContext, path)?.first ?: return Result.failure()
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        setPhase("downloading")
        val raw = bridge.forceDownloadFromEpub(localFile.absolutePath, outputDir)
        if (isStopped) {
            jobDao.update(
                job.copy(
                    status = "cancelled",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("cancelled")
            return Result.failure()
        }
        val result = JSONObject(raw)
        if (!result.optBoolean("ok")) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = result.optString("error", "unknown"),
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }

        val title = result.optString("title", existing?.title ?: "story")
        val internalPath = result.optString("path", "")
        if (internalPath.isNotBlank() && File(internalPath).exists()) {
            if (isStopped) {
                jobDao.update(
                    job.copy(
                        status = "cancelled",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                setPhase("cancelled")
                return Result.failure()
            }
            setPhase("processing")
            val savedOutputDir = SettingsActivity.getOutputDir(applicationContext)
            val finalPath = try {
                StorageBridge.copyToOutputDir(applicationContext, File(internalPath), savedOutputDir)
            } finally {
                File(internalPath).delete()
            }
            if (isStopped) {
                jobDao.update(
                    job.copy(
                        status = "cancelled",
                        finishedAt = System.currentTimeMillis()
                    )
                )
                setPhase("cancelled")
                return Result.failure()
            }
            setPhase("copying")
            val updatedEntity = if (existing != null) {
                existing.copy(
                    title = title,
                    filePath = finalPath,
                    lastModified = result.optLong("modified", System.currentTimeMillis()),
                    sizeBytes = result.optLong("size", 0L),
                    coverData = result.optString("cover", existing.coverData ?: ""),
                    url = result.optString("url", existing.url ?: ""),
                    chapters = result.optInt("chapters", existing.chapters)
                )
            } else {
                BookItem(
                    title = title,
                    author = "",
                    uriString = finalPath,
                    lastModified = result.optLong("modified", System.currentTimeMillis()),
                    sizeBytes = result.optLong("size", 0L),
                    coverUriString = result.optString("cover", ""),
                    url = result.optString("url", ""),
                    chapters = result.optInt("chapters", 0),
                    sourceUriString = finalPath
                ).toEntity()
            }
            val current = jobDao.getById(job.id)
            if (current?.status == "cancelled") {
                setPhase("cancelled")
                return Result.failure()
            }
            val before = bookDao.findByFilePath(finalPath)
            android.util.Log.d("FFF-Dup", "handleForceDownload title=${updatedEntity.title} path=${finalPath} existingId=${existing?.id} before=${before?.id}")
            val saved = upsertBook(bookDao, updatedEntity, finalPath)
            android.util.Log.d("FFF-Dup", "handleForceDownload inserted id=${saved.id}")
            jobDao.update(
                job.copy(
                    bookId = saved.id,
                    status = "success",
                    outputPath = finalPath,
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("completed", indeterminate = false)
            return Result.success()
        }

        jobDao.update(
            job.copy(
                status = "success",
                finishedAt = System.currentTimeMillis()
            )
        )
        setPhase("completed", indeterminate = false)
        return Result.success()
    }

    private suspend fun handleMetadata(
        url: String,
        jobDao: DownloadJobDao,
        job: DownloadJobEntity
    ): Result {
        if (url.isBlank()) {
            jobDao.update(
                job.copy(
                    status = "failed",
                    error = "Missing URL",
                    finishedAt = System.currentTimeMillis()
                )
            )
            setPhase("failed")
            return Result.failure()
        }
        val bridge = PythonBridge(applicationContext)
        setPhase("fetching_metadata")
        val raw = bridge.fanficfareMetadata(url)
        val result = JSONObject(raw)
        val status = if (result.optBoolean("ok")) "success" else "failed"
        val errorMessage = result.optString("error", "")
        if (errorMessage.isNotBlank()) {
            android.util.Log.e("FanFicFareWorker", "FanFicFare error: $errorMessage")
        }
        jobDao.update(
            job.copy(
                status = status,
                error = errorMessage.ifBlank { null },
                resultJson = if (result.optBoolean("ok")) result.toString() else null,
                finishedAt = System.currentTimeMillis()
            )
        )
        setPhase(if (result.optBoolean("ok")) "completed" else "failed", indeterminate = !result.optBoolean("ok"))
        return if (result.optBoolean("ok")) Result.success() else Result.failure()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
            val channel = NotificationChannel(CHANNEL_ID, "FanFicFare Worker", android.app.NotificationManager.IMPORTANCE_LOW)
            manager.createNotificationChannel(channel)
        }
    }

    private fun chooseCover(existing: String?, returned: String?): String {
        val newCover = returned?.trim().orEmpty()
        return if (newCover.isNotEmpty()) newCover else existing?.trim().orEmpty()
    }
}
