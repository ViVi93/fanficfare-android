package com.vivi.aharana.data.local

import androidx.lifecycle.LiveData
import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update

@Dao
interface DownloadJobDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(job: DownloadJobEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(jobs: List<DownloadJobEntity>): List<Long>

    @Update
    suspend fun update(job: DownloadJobEntity)

    @Query("SELECT * FROM download_jobs WHERE id = :id LIMIT 1")
    suspend fun getById(id: Long): DownloadJobEntity?

    @Query("SELECT * FROM download_jobs WHERE bookId = :bookId ORDER BY createdAt ASC")
    fun observeByBookId(bookId: Long): LiveData<List<DownloadJobEntity>>

    @Query("SELECT * FROM download_jobs WHERE status = :status ORDER BY createdAt ASC")
    fun observeByStatus(status: String): LiveData<List<DownloadJobEntity>>

    @Query("SELECT * FROM download_jobs ORDER BY createdAt ASC")
    fun observeAll(): LiveData<List<DownloadJobEntity>>

    @Query("SELECT * FROM download_jobs WHERE workId = :workId LIMIT 1")
    suspend fun findByWorkId(workId: String): DownloadJobEntity?

    /**
     * Older rows for the same story that a successful run has made irrelevant.
     * Used to clear stale failed/queued rows for a story that has since downloaded.
     */
    @Query(
        "SELECT * FROM download_jobs WHERE inputUrl = :url AND id != :keepId " +
            "AND status IN ('queued','waiting','running','failed')"
    )
    suspend fun findSuperseded(url: String, keepId: Long): List<DownloadJobEntity>

    @Query("SELECT * FROM download_jobs ORDER BY createdAt ASC")
    suspend fun getAll(): List<DownloadJobEntity>

    @Query("SELECT * FROM download_jobs WHERE status = :status ORDER BY createdAt ASC")
    suspend fun getByStatus(status: String): List<DownloadJobEntity>

    @Delete
    suspend fun delete(job: DownloadJobEntity)

    @Query("DELETE FROM download_jobs")
    suspend fun clear()
}
