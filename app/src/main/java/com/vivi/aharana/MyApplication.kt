package com.vivi.aharana

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
        applySavedThemeMode()
        // Dynamic colour (Material You) is applied per-activity in BaseActivity, not here:
        // MDC applies dynamic colour before activities are created, so applying it from the
        // Application would be overwritten by the per-activity theme decision
        // (AMOLED vs normal, Material You vs system contrast).
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

    /**
     * Re-applies the saved theme mode on every process start.
     *
     * AppCompatDelegate's night mode is process-wide and resets on restart, and it was only ever
     * set from the Settings screen, so a Light or Dark choice silently reverted to the system
     * setting on the next launch.
     */
    private fun applySavedThemeMode() {
        val mode = getSharedPreferences(BaseActivity.PREFS, MODE_PRIVATE)
            .getString(BaseActivity.KEY_THEME_MODE, BaseActivity.THEME_SYSTEM)
        androidx.appcompat.app.AppCompatDelegate.setDefaultNightMode(
            when (mode) {
                BaseActivity.THEME_LIGHT -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_NO
                BaseActivity.THEME_DARK,
                BaseActivity.THEME_AMOLED -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_YES
                else -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
        )
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
