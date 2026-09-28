plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android { namespace = "com.atlas.trading"; compileSdk = 35
    defaultConfig { applicationId = "com.atlas.trading"; minSdk = 26; targetSdk = 35; versionCode = 1045; versionName = "3.10.45" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.12.1")
}
