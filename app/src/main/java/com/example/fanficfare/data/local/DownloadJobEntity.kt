package com.example.fanficfare.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "download_jobs",
    indices = [Index(value = ["bookId"])]
)
data class DownloadJobEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    val bookId: Long = 0,
    val type: String = "",
    val status: String = "",
    val inputUrl: String? = null,
    val inputPath: String? = null,
    val outputPath: String? = null,
    val error: String? = null,
    val createdAt: Long = 0L,
    val finishedAt: Long? = null,
    val workId: String? = null,
    val resultJson: String? = null
)
