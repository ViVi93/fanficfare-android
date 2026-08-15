package com.example.fanficfare

import org.json.JSONObject

class PythonBridge {
    fun fanficfareDownload(url: String, outDir: String): String {
        return JSONObject().put("ok", false).put("error", "Python bridge not enabled in this build").toString()
    }
    fun fanficfareMetadata(url: String): String {
        return JSONObject().put("ok", false).put("error", "Python bridge not enabled in this build").toString()
    }
}
