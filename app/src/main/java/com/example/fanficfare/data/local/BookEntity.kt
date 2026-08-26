package com.example.fanficfare.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "books",
    indices = [
        Index(value = ["url"]),
        Index(value = ["filePath"])
    ]
)
data class BookEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    val title: String,
    val author: String,
    val url: String?,
    val filePath: String,
    val sourcePath: String?,
    val lastModified: Long,
    val sizeBytes: Long,
    val coverData: String?,
    val chapters: Int,
    val addedAt: Long
)
