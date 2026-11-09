package com.example.fx;

import android.content.Context;
import android.content.SharedPreferences;

class Storage {
    SharedPreferences open(Context ctx) {
        return ctx.getSharedPreferences("prefs", Context.MODE_WORLD_READABLE);
    }
}
