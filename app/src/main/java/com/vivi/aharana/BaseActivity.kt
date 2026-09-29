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
 */
open class BaseActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
    }

    /**
     * Pads [view]'s top by the status-bar inset. Use on app bars / toolbars so their
     * background extends behind the status bar while the content stays clear of it.
     */
    protected fun applyTopInset(view: View) {
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val top = insets.getInsets(WindowInsetsCompat.Type.systemBars()).top
            v.updatePadding(top = top)
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }

    /**
     * Pads [view]'s bottom by the navigation-bar inset. Use on scrolling content that has
     * `android:clipToPadding="false"`, so it still scrolls *under* the gesture bar while the
     * last row remains reachable.
     */
    protected fun applyBottomInset(view: View) {
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bottom = insets.getInsets(WindowInsetsCompat.Type.systemBars()).bottom
            v.updatePadding(bottom = bottom)
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }

    /** Pads [view]'s left/right by the system-bar insets (landscape, display cutouts). */
    protected fun applyHorizontalInsets(view: View) {
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.updatePadding(left = bars.left, right = bars.right)
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }

    /**
     * Pads [view] on all sides by the system-bar insets. Use for a root whose content should
     * stay fully inside the safe area (no drawing behind the bars).
     */
    protected fun applySystemBarInsets(view: View) {
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.updatePadding(
                left = bars.left,
                top = bars.top,
                right = bars.right,
                bottom = bars.bottom
            )
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }

    /**
     * Adds the IME (keyboard) height to [view]'s bottom padding on top of the navigation-bar
     * inset, so form fields are not hidden behind the keyboard.
     */
    protected fun applyImeBottomInset(view: View) {
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.updatePadding(bottom = maxOf(bars.bottom, ime.bottom))
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }
}
