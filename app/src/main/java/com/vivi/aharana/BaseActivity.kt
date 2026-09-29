package com.vivi.aharana

import android.os.Bundle
import android.view.View
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding

/**
 * Shared base for every screen.
 *
 * Android 15 (API 35) enforces edge-to-edge for apps that target SDK 35 and ignores
 * `WindowCompat.setDecorFitsSystemWindows(window, true)`, so the old per-activity opt-out
 * is both deprecated and ineffective. We call [enableEdgeToEdge] exactly once here and let
 * each screen inset the views that actually need it via the helpers below, rather than
 * relying on `android:fitsSystemWindows` to guess.
 *
 * The helpers add the system insets *on top of* the padding already declared in XML (the base
 * padding is captured once, so repeated inset callbacks stay idempotent instead of accumulating).
 */
open class BaseActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
    }

    /** Pads [view]'s top by the status-bar inset. Use on app bars so their background extends
     *  behind the status bar while the content stays clear of it. */
    protected fun applyTopInset(view: View) =
        applyInsets(view, top = true, bottom = false, horizontal = false)

    /** Pads [view]'s bottom by the navigation-bar inset. Use on content that should keep its
     *  last row reachable above the gesture bar. */
    protected fun applyBottomInset(view: View) =
        applyInsets(view, top = false, bottom = true, horizontal = false)

    /** Pads [view]'s left/right by the system-bar insets (landscape, display cutouts). */
    protected fun applyHorizontalInsets(view: View) =
        applyInsets(view, top = false, bottom = false, horizontal = true)

    /** Pads [view] on all sides by the system-bar insets, for a root whose content should stay
     *  fully inside the safe area. Set [includeIme] on form screens so the keyboard cannot hide
     *  the focused field (requires `android:windowSoftInputMode="adjustResize"`). */
    protected fun applySystemBarInsets(view: View, includeIme: Boolean = false) =
        applyInsets(view, top = true, bottom = true, horizontal = true, includeIme = includeIme)

    private fun applyInsets(
        view: View,
        top: Boolean,
        bottom: Boolean,
        horizontal: Boolean,
        includeIme: Boolean = false
    ) {
        // Captured once: the padding declared in XML is the baseline the insets are added to.
        val baseLeft = view.paddingLeft
        val baseTop = view.paddingTop
        val baseRight = view.paddingRight
        val baseBottom = view.paddingBottom

        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val imeBottom = if (includeIme) {
                insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            } else {
                0
            }
            v.updatePadding(
                left = baseLeft + if (horizontal) bars.left else 0,
                top = baseTop + if (top) bars.top else 0,
                right = baseRight + if (horizontal) bars.right else 0,
                bottom = baseBottom + if (bottom) maxOf(bars.bottom, imeBottom) else 0
            )
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }
}
