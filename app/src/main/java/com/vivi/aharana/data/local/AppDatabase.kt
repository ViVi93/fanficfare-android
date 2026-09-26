package com.vivi.aharana.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        BookEntity::class,
        DownloadJobEntity::class
    ],
    version = 5,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun bookDao(): BookDao
    abstract fun downloadJobDao(): DownloadJobDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        /**
         * Makes filePath unique, so one file can only ever have one library row.
         *
         * Duplicates already in the table have to go before the index can be
         * created, so the newest row per path is kept and the rest are dropped.
         * The old non-unique index has the same name, so it is dropped first --
         * "CREATE UNIQUE INDEX IF NOT EXISTS" would otherwise silently leave the
         * non-unique one in place and Room's schema check would fail.
         */
        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "DELETE FROM books WHERE id NOT IN (SELECT MAX(id) FROM books GROUP BY filePath)"
                )
                db.execSQL("DROP INDEX IF EXISTS index_books_filePath")
                db.execSQL(
                    "CREATE UNIQUE INDEX IF NOT EXISTS index_books_filePath ON books (filePath)"
                )
            }
        }

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "fanficfare_database"
                )
                    .addMigrations(MIGRATION_4_5)
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}
