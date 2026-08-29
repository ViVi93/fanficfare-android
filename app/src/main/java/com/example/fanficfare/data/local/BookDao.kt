package com.example.fanficfare.data.local

import androidx.lifecycle.LiveData
import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update

@Dao
interface BookDao {

    @Query("SELECT * FROM books ORDER BY lastModified ASC")
    fun observeAll(): LiveData<List<BookEntity>>

    @Query("SELECT * FROM books ORDER BY lastModified ASC")
    suspend fun getAll(): List<BookEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(book: BookEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(books: List<BookEntity>)

    @Update
    suspend fun update(book: BookEntity)

    @Delete
    suspend fun delete(book: BookEntity)

    @Query("DELETE FROM books")
    suspend fun clear()

    @Query("SELECT * FROM books WHERE url = :url LIMIT 1")
    suspend fun findByUrl(url: String?): BookEntity?

    @Query("SELECT * FROM books WHERE filePath = :filePath LIMIT 1")
    suspend fun findByFilePath(filePath: String?): BookEntity?

    @Query("SELECT * FROM books WHERE id = :id LIMIT 1")
    suspend fun findById(id: Long): BookEntity?
}
