package com.example.fanficfare

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import org.json.JSONObject

class PythonBridge(private val context: Context) {

    private var module: PyObject? = null
    private var initError: String? = null

    init {
        try {
            val python = Python.getInstance()
            val sys = python.getModule("sys")
            val path = context.filesDir.absolutePath + "/python"
            sys.callAttr("path", "append", path)
            module = python.getModule("fanficfare_bridge")
        } catch (e: Exception) {
            initError = e.message ?: "unknown"
        }
    }

    fun fanficfareDownload(url: String, outDir: String): String =
        safeCall("download_story", url, outDir)

    fun fanficfareMetadata(url: String): String =
        safeCall("get_metadata", url)

    fun fanficfareListSites(): String =
        safeCall("list_sites")

    fun scanEpubDir(directory: String): String =
        safeCall("scan_epub_dir", directory)

    fun saveLibraryIndex(indexPath: String, booksJson: String): String =
        safeCall("save_library_index", indexPath, booksJson)

    fun loadLibraryIndex(indexPath: String): String =
        safeCall("load_library_index", indexPath)

    fun getEpubUpdateUrl(epubPath: String): String =
        safeCall("get_epub_update_url", epubPath)

    fun deleteEpub(epubPath: String): String =
        safeCall("delete_epub", epubPath)

    fun updateEpubFromPath(epubPath: String, outDir: String): String =
        safeCall("update_epub_from_path", epubPath, outDir)

    fun forceDownloadFromEpub(epubPath: String, outDir: String): String =
        safeCall("force_download_from_epub", epubPath, outDir)

    private fun safeCall(method: String, vararg args: Any): String {
        val mod = module
        if (mod == null) {
            return JSONObject().put("ok", false).put("error", "Bridge init failed: $initError").toString()
        }
        return try {
            val result = mod.callAttr(method, *args)
            result.toString()
        } catch (e: Throwable) {
            JSONObject().put("ok", false).put("error", e.message ?: "unknown").toString()
        }
    }
}
