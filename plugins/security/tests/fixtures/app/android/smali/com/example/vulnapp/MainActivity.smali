.class public Lcom/example/vulnapp/MainActivity;
.super Landroid/app/Activity;

.field private static final AWS_KEY:Ljava/lang/String; = "@@AWS_KEY@@"

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method public hash(Ljava/lang/String;)[B
    .registers 4
    const-string v0, "MD5"
    invoke-static {v0}, Ljava/security/MessageDigest;->getInstance(Ljava/lang/String;)Ljava/security/MessageDigest;
    move-result-object v0
    invoke-virtual {p1}, Ljava/lang/String;->getBytes()[B
    move-result-object v1
    invoke-virtual {v0, v1}, Ljava/security/MessageDigest;->digest([B)[B
    move-result-object v0
    return-object v0
.end method

.method public log(Ljava/lang/String;)V
    .registers 3
    const-string v0, "http://api.example.com/v1/login"
    invoke-static {v0, p1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method
