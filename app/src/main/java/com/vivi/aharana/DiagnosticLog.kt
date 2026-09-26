package com.vivi.aharana

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object DiagnosticLog {
    private const val FILE_NAME = "fanficfare_debug.log"
    private val timeFormat = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

    fun getFile(context: Context): File {
        val dir = context.getExternalFilesDir(null) ?: context.filesDir
        return File(dir, FILE_NAME)
    }

    fun clear(context: Context) {
        getFile(context).delete()
    }

    fun append(context: Context, tag: String, message: String) {
        try {
            val line = String.format(
                Locale.US,
                "[%s] %s: %s%n",
                timeFormat.format(Date()),
                tag,
                message.replace("\n", " ").replace("\r", " ")
            )
            getFile(context).appendText(line)
        } catch (e: Exception) {
            // never let diagnostics break the app
        }
    }

    fun appendException(context: Context, tag: String, message: String, e: Throwable) {
        val sb = StringBuilder()
        sb.append(message)
        sb.append(" | exception=").append(e.javaClass.simpleName)
        sb.append(" | msg=").append(e.message ?: "null")
        val stack = e.stackTrace
        if (stack.isNotEmpty()) {
            sb.append(" | at=").append(stack[0].className).append('.').append(stack[0].methodName)
        }
        append(context, tag, sb.toString())
    }

    fun getText(context: Context): String {
        return try { getFile(context).readText() } catch (e: Exception) { "" }
    }

    /**
     * Result of [getTail]: the tail lines and the total line count.
     */
    data class TailResult(val lines: String, val totalCount: Int)

    /**
     * Read at most [maxLines] from the end of the log file, using a sliding
     * window that never holds more than [maxLines] strings in memory at once.
     *
     * Used by the Diagnostics screen to avoid TextView OOM crashes when the
     * log file is very large.
     *
     * Returns both the tail content and the total line count.
     *
     * The full log remains available via the Share button, which writes the
     * complete file to an external intent.
     */
    fun getTail(context: Context, maxLines: Int = 30): TailResult {
        val file = getFile(context)
        if (!file.exists() || file.length() == 0L) return TailResult("", 0)
        return try {
            val lines = mutableListOf<String>()
            var totalCount = 0
            file.forEachLine { line ->
                totalCount++
                lines.add(line)
                if (lines.size > maxLines) lines.removeAt(0)
            }
            TailResult(lines.joinToString("\n"), totalCount)
        } catch (e: Exception) {
            TailResult("", 0)
        }
    }
}
