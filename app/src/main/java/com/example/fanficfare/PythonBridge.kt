package com.example.fanficfare

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import org.json.JSONObject

class PythonBridge(private val context: Context) {

    private val module: PyObject by lazy {
        val python = Python.getInstance()
        val sys = python.getModule("sys")
        val path = context.filesDir.absolutePath + "/python"
        sys.callAttr("path", "append", path)
        python.getModule("fanficfare_bridge")
    }

    fun fanficfareDownload(url: String, outDir: String): String =
        call("download_story", url, outDir)

    fun fanficfareMetadata(url: String): String =
        call("get_metadata", url)

    fun fanficfareListSites(): String =
        call("list_sites")

    fun scanEpubDir(directory: String): String =
        call("scan_epub_dir", directory)

    fun saveLibraryIndex(indexPath: String, booksJson: String): String =
        call("save_library_index", indexPath, booksJson)

    fun loadLibraryIndex(indexPath: String): String =
        call("load_library_index", indexPath)

    fun getEpubUpdateUrl(epubPath: String): String =
        call("get_epub_update_url", epubPath)

    fun deleteEpub(epubPath: String): String =
        call("delete_epub", epubPath)

    fun updateEpubFromPath(epubPath: String, outDir: String): String =
        call("update_epub_from_path", epubPath, outDir)

    fun forceDownloadFromEpub(epubPath: String, outDir: String): String =
        call("force_download_from_epub", epubPath, outDir)

    private fun call(method: String, vararg args: Any): String {
        return try {
            val result = module.callAttr(method, *args)
            result.toString()
        } catch (e: Exception) {
            JSONObject().put("ok", false).put("error", e.message ?: "unknown").toString()
        }
    }
}
