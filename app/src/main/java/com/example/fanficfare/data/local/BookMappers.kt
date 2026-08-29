package com.example.fanficfare.data.local

import com.example.fanficfare.model.BookItem

fun BookItem.toEntity(now: Long = System.currentTimeMillis()): BookEntity = BookEntity(
    title = title,
    author = author,
    url = url.ifBlank { null },
    filePath = uriString,
    sourcePath = sourceUriString,
    lastModified = lastModified,
    sizeBytes = sizeBytes,
    coverData = coverUriString,
    chapters = chapters,
    addedAt = now
)

fun BookEntity.toBookItem(): BookItem = BookItem(
    title = title,
    author = author,
    uriString = filePath,
    lastModified = lastModified,
    sizeBytes = sizeBytes,
    coverUriString = coverData,
    url = url.orEmpty(),
    chapters = chapters,
    sourceUriString = sourcePath,
    addedAt = if (addedAt > 0) addedAt else lastModified
)
