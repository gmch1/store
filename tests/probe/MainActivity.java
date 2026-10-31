package com.ming.store.probe;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("Store validation probe\nInstalled successfully");
        text.setTextSize(24);
        text.setPadding(32, 64, 32, 32);
        setContentView(text);
    }
}
