package com.example.fanficfare

import android.app.Application
import java.io.File
import java.io.FileWriter
import java.io.PrintWriter
import java.text.SimpleDateFormat
import java.util.*

class MyApplication : Application(), androidx.work.Configuration.Provider {
    private val originalHandler = Thread.getDefaultUncaughtExceptionHandler()

    override fun onCreate() {
        super.onCreate()
        com.google.android.material.color.DynamicColors.applyToActivitiesIfAvailable(this)
        android.util.Log.d("FFF-App", "WorkManager initialized=${androidx.work.WorkManager.getInstance(this)}")

        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                logCrash(throwable, thread.name)
            } finally {
                try {
                    originalHandler?.uncaughtException(thread, throwable)
                } catch (e: Exception) {
                    // ignore secondary logging failures
                }
            }
        }
    }

    override val workManagerConfiguration: androidx.work.Configuration = androidx.work.Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.DEBUG)
            .build()

    private fun logCrash(throwable: Throwable, threadName: String) {
        try {
            val crashDir = File(getExternalFilesDir(null), "fanficfare_crashes")
            if (!crashDir.exists()) {
                crashDir.mkdirs()
            }

            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val crashFile = File(crashDir, "crash_$timestamp.txt")

            FileWriter(crashFile).use { writer ->
                PrintWriter(writer).use { pw ->
                    pw.println("=== Crash Log ===")
                    pw.println("Timestamp: ${Date()}")
                    pw.println("Thread: $threadName")
                    pw.println()
                    throwable.printStackTrace(pw)
                    pw.println()
                    pw.println("=== Cause ===")
                    throwable.cause?.printStackTrace(pw)
                }
            }
        } catch (e: Exception) {
            // never let diagnostics break the app
        }
    }
}
