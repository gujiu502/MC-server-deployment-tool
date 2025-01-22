import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk, filedialog, StringVar
import requests
import json
import threading
import queue
import sys

CONFIG_FILE = "config.json"
CACHE_FILE = "cache.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            # 加载安装路径和启动路径
            install_path_var.set(config.get("install_path", os.getcwd()))  # 默认为当前工作目录
            launcher_path_var.set(config.get("launcher_path", os.getcwd()))  # 默认为当前工作目录
            return config
    return {}

def save_config(config):
    config["install_path"] = install_path_var.get()
    config["launcher_path"] = launcher_path_var.get()  # 保存启动路径
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

def get_minecraft_versions():
    cache = load_cache()
    if "minecraft_versions" in cache:
        return cache["minecraft_versions"]

    try:
        response = requests.get("https://launchermeta.mojang.com/mc/game/version_manifest.json")
        response.raise_for_status()
        versions = response.json().get("versions", [])
        mc_versions = [version["id"] for version in versions if version["type"] == "release"]
        save_cache({"minecraft_versions": mc_versions})  # 缓存 Minecraft 版本
        return mc_versions
    except requests.RequestException as e:
        messagebox.showerror("错误", f"无法获取 Minecraft 版本列表: {e}")
        return []

def get_available_forge_versions():
    try:
        response = requests.get("https://api.github.com/repos/gujiu502/minecraft_Forge_Servers_installer/contents/")
        response.raise_for_status()
        files = response.json()
        forge_versions = [file['name'] for file in files if file['name'].startswith('forge-') and file['name'].endswith('-installer.jar')]
        return forge_versions
    except requests.RequestException as e:
        print(f"无法获取 Forge 版本，状态码: {e}")
        messagebox.showerror("错误", "无法获取 Forge 版本列表")
        return []

def log_message(message, is_launcher=False):
    if is_launcher:
        cmd_text_launcher.insert(tk.END, message + "\n")  # 输出到启动器的 CMD 区域
    else:
        cmd_text.insert(tk.END, message + "\n")  # 输出到部署系统的 CMD 区域
    cmd_text_launcher.see(tk.END)  # 自动滚动到最新输出
    cmd_text.see(tk.END)  # 自动滚动到最新输出

def download_server(mc_version, server_type, install_path, progress_queue):
    if server_type == "forge":
        available_forge_versions = get_available_forge_versions()
        if not available_forge_versions:
            messagebox.showerror("错误", "未找到可用的 Forge 版本")
            return None

        for forge_version in available_forge_versions:
            if mc_version in forge_version:
                url = f"https://raw.githubusercontent.com/gujiu502/minecraft_Forge_Servers_installer/main/{forge_version}"
                break
        else:
            messagebox.showerror("错误", "未找到匹配的 Forge 版本")
            return None

    elif server_type == "fabric":
        fabric_loader_version = "0.16.10"
        fabric_installer_version = "1.0.1"
        url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{fabric_loader_version}/{fabric_installer_version}/server/jar"
        
    else:
        messagebox.showerror("错误", "未知的服务器类型")
        return None

    log_message(f"正在下载 {server_type} 服务器文件...")
    file_path = os.path.join(install_path, f"{server_type}-installer.jar")

    try:
        response = requests.get(url, stream=True, timeout=10)  # 设置超时
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded_size += len(chunk)
                progress = (downloaded_size / total_size) * 100 if total_size > 0 else 0
                progress_queue.put(progress)

        log_message(f"{server_type} 安装程序下载完成: {file_path}")
        return file_path
    except requests.Timeout:
        messagebox.showerror("错误", "下载超时，请检查网络连接")
        return None
    except requests.RequestException as e:
        messagebox.showerror("错误", f"下载失败: {e}")
        return None

def setup_server(version, server_type, install_path):
    log_message(f"正在安装 {server_type} 服务器...")
    installer_path = os.path.join(install_path, f"{server_type}-installer.jar")
    if not os.path.exists(installer_path):
        messagebox.showerror("错误", f"{server_type} 安装程序不存在")
        return
    try:
        if server_type == "forge":
            log_message("正在运行 Forge 安装程序...")
            subprocess.run(["javaw", "-jar", installer_path, "--installServer"], cwd=install_path, check=True)
        elif server_type == "fabric":
            log_message("正在运行 Fabric 安装程序...")
            subprocess.run(["javaw", "-jar", installer_path, "server", version], cwd=install_path, check=True)
        log_message(f"{server_type} 安装完成")

        # 生成 eula.txt 文件并写入同意内容
        eula_file_path = os.path.join(install_path, "eula.txt")
        with open(eula_file_path, "w") as eula_file:
            eula_file.write("eula=true\n")  # 写入同意内容
        log_message("已生成 eula.txt 文件并同意 EULA")
    except subprocess.CalledProcessError as e:
        messagebox.showerror("错误", f"{server_type} 安装失败: {e}")
        log_message(f"安装失败: {e}")

def deploy_server():
    deploy_button.config(state=tk.DISABLED)  # 禁用按钮
    mc_version = version_var.get()
    server_type = server_type_var.get()
    install_path = install_path_var.get()

    if not os.path.isdir(install_path):
        messagebox.showerror("错误", "安装路径无效")
        deploy_button.config(state=tk.NORMAL)  # 启用按钮
        return

    progress_bar.pack(pady=10, fill="x")
    progress_bar.start()
    log_message("开始部署服务器...")

    # 使用线程来下载和安装服务器
    progress_queue = queue.Queue()  # 创建队列用于进度更新

    def run_deployment():
        file_path = download_server(mc_version, server_type, install_path, progress_queue)
        if not file_path:
            log_message("部署失败: 服务器文件下载失败")
            progress_bar.stop()
            return

        try:
            setup_server(mc_version, server_type, install_path)
        except Exception as e:
            log_message(f"部署失败: {e}")
            messagebox.showerror("错误", f"服务器安装失败: {e}")
            progress_bar.stop()
            return

        progress_bar.stop()
        log_message("部署完成")
        deploy_button.config(state=tk.NORMAL)  # 启用按钮

    def update_progress():
        try:
            while True:
                progress = progress_queue.get_nowait()  # 获取队列中的进度
                progress_bar['value'] = progress  # 更新进度条
        except queue.Empty:
            pass
        root.after(100, update_progress)  # 每100毫秒更新一次进度

    threading.Thread(target=run_deployment, daemon=True).start()
    update_progress()  # 启动进度更新

def browse_directory():
    directory = filedialog.askdirectory()
    if directory:
        install_path_var.set(directory)

def browse_directory_for_launcher():
    directory = filedialog.askdirectory()
    if directory:
        launcher_path_var.set(directory)

# 添加按钮以打开模组文件夹
def open_mod_folder():
    mod_folder_path = os.path.join(launcher_path_var.get(), "mods")  # 假设模组文件夹名为 "mods"
    if not os.path.exists(mod_folder_path):
        os.makedirs(mod_folder_path)  # 创建模组文件夹
        log_message(f"创建模组文件夹: {mod_folder_path}")
    os.startfile(mod_folder_path)  # 打开模组文件夹
    log_message(f"打开模组文件夹: {mod_folder_path}")

# 添加按钮以打开地图文件夹
def open_world_folder():
    world_folder_path = os.path.join(launcher_path_var.get(), "world")  # 假设地图文件夹名为 "world"
    if not os.path.exists(world_folder_path):
        os.makedirs(world_folder_path)  # 创建地图文件夹
        log_message(f"创建地图文件夹: {world_folder_path}")
    os.startfile(world_folder_path)  # 打开地图文件夹
    log_message(f"打开地图文件夹: {world_folder_path}")

# 添加按钮以打开插件文件夹
def open_plugin_folder():
    server_directory = install_path_var.get()  # 获取服务器所在的文件夹路径
    os.startfile(server_directory)  # 打开服务器所在的文件夹
    log_message(f"打开服务器所在的文件夹: {server_directory}")

# 添加按钮以打开设置文件夹
def open_settings_folder():
    settings_folder_path = os.path.join(launcher_path_var.get(), "config")  # 假设设置文件夹名为 "config"
    if not os.path.exists(settings_folder_path):
        os.makedirs(settings_folder_path)  # 创建设置文件夹
        log_message(f"创建设置文件夹: {settings_folder_path}")
    os.startfile(settings_folder_path)  # 打开设置文件夹
    log_message(f"打开设置文件夹: {settings_folder_path}")

root = tk.Tk()
root.title("Minecraft 服务器部署")
root.geometry("400x600")

# 创建标签页
notebook = ttk.Notebook(root)
notebook.pack(fill='both', expand=True)

# 创建服务器部署标签页
deploy_frame = ttk.Frame(notebook)
notebook.add(deploy_frame, text="服务器部署")

# 在创建服务器部署标签页之前定义 server_type_var
server_type_var = StringVar(value="forge")  # 默认选择 forge

# 在服务器部署标签页中添加选择服务器类型的下拉框
tk.Label(deploy_frame, text="选择服务器类型:", font=("Arial", 12)).pack(pady=10)
ttk.Combobox(deploy_frame, textvariable=server_type_var, values=["fabric", "forge"], state="readonly").pack(pady=5)

# 创建 UI 组件
tk.Label(deploy_frame, text="选择 Minecraft 版本:", font=("Arial", 12)).pack(pady=10)
version_var = tk.StringVar(value="1.16.5")  # 默认版本
ttk.Combobox(deploy_frame, textvariable=version_var, values=get_minecraft_versions(), state="readonly").pack(pady=5)

tk.Label(deploy_frame, text="安装路径:", font=("Arial", 12)).pack(pady=10)
install_path_var = tk.StringVar(value=os.getcwd())  # 默认路径
tk.Entry(deploy_frame, textvariable=install_path_var, width=40).pack(pady=5)
tk.Button(deploy_frame, text="浏览", command=browse_directory).pack(pady=5)

# 创建"部署服务器"按钮并将其赋值给 deploy_button 变量
deploy_button = tk.Button(deploy_frame, text="部署服务器", command=deploy_server, font=("Arial", 12))
deploy_button.pack(pady=20)

# 添加进度条
progress_bar = ttk.Progressbar(deploy_frame, mode="determinate")  # 设置为确定模式
progress_bar.pack(pady=10, fill="x")

# 嵌入式 CMD 显示区域
cmd_text = tk.Text(deploy_frame, height=10, width=50)
cmd_text.pack(side=tk.BOTTOM, pady=10)  # 将 cmd_text 放在底部

# 在创建服务器启动器标签页之前定义 launcher_path_var
launcher_path_var = tk.StringVar(value=os.getcwd())  # 默认路径

# 在创建服务器启动器标签页之前定义 port_var
port_var = tk.StringVar(value="25565")  # 默认端口为 25565

# 创建服务器启动器标签页
launcher_frame = ttk.Frame(notebook)
notebook.add(launcher_frame, text="服务器启动器")

# 在服务器启动器标签页中添加选择服务器类型的下拉框
tk.Label(launcher_frame, text="选择服务器类型:", font=("Arial", 12)).pack(pady=10)
ttk.Combobox(launcher_frame, textvariable=server_type_var, values=["fabric", "forge"], state="readonly").pack(pady=5)

# 添加服务器启动器的路径输入和启动按钮
path_frame = tk.Frame(launcher_frame)
path_frame.pack(pady=5)

tk.Label(path_frame, text="服务器路径:", font=("Arial", 12)).pack(side=tk.LEFT)  # 标签
tk.Entry(path_frame, textvariable=launcher_path_var, width=30).pack(side=tk.LEFT, padx=5)  # 输入框
tk.Button(path_frame, text="浏览", command=browse_directory_for_launcher).pack(side=tk.LEFT, padx=5)  # 浏览按钮

# 添加自定义内存输入框
memory_frame = tk.Frame(launcher_frame)
memory_frame.pack(pady=5)

tk.Label(memory_frame, text="自定义内存 (MB):", font=("Arial", 12)).pack(side=tk.LEFT)  # 标签
memory_var = tk.StringVar(value="1024")  # 默认内存值
tk.Entry(memory_frame, textvariable=memory_var, width=10).pack(side=tk.LEFT, padx=5)  # 将宽度设置为较小的值

# 创建一个框架用于自定义端口的标签和输入框
port_frame = tk.Frame(launcher_frame)
port_frame.pack(pady=5)

tk.Label(port_frame, text="自定义端口:", font=("Arial", 12)).pack(side=tk.LEFT)  # 标签
tk.Entry(port_frame, textvariable=port_var, width=10).pack(side=tk.LEFT, padx=5)  # 输入框

# 创建一个框架用于按钮的 2x2 布局
button_frame = tk.Frame(launcher_frame)
button_frame.pack(pady=5)

# 第一行按钮
row1_frame = tk.Frame(button_frame)
row1_frame.pack(side=tk.TOP)

tk.Button(row1_frame, text="打开 模组 文件夹", command=open_mod_folder).pack(side=tk.LEFT, padx=5)  # 打开模组文件夹按钮
tk.Button(row1_frame, text="打开 地图 文件夹", command=open_world_folder).pack(side=tk.LEFT, padx=5)  # 打开地图文件夹按钮

# 第二行按钮
row2_frame = tk.Frame(button_frame)
row2_frame.pack(side=tk.TOP)

tk.Button(row2_frame, text="打开 服务器 文件夹", command=open_plugin_folder).pack(side=tk.LEFT, padx=5)  # 打开服务器文件夹按钮
tk.Button(row2_frame, text="打开 设置 文件夹", command=open_settings_folder).pack(side=tk.LEFT, padx=5)  # 打开设置文件夹按钮

# 将启动服务器按钮移动到最后
tk.Button(launcher_frame, text="启动服务器", command=lambda: start_server(launcher_path_var.get(), memory_var.get(), server_type_var.get())).pack(pady=20)  # 启动服务器按钮

# 在启动器部分添加嵌入式 CMD 显示区域
cmd_text_launcher = tk.Text(launcher_frame, height=10, width=50)
cmd_text_launcher.pack(side=tk.BOTTOM, pady=10)  # 将 cmd_text_launcher 放在底部

def start_server(server_path, memory, server_type):
    # 禁用弹窗
    os.environ['PYTHONUNBUFFERED'] = '1'
    
    # 指定 Java 的路径
    java_path = r"C:\Program Files\Java\jdk-11\bin\javaw.exe"
    
    if server_type == "fabric":
        fabric_installer_path = os.path.join(server_path, "fabric-installer.jar")  # 假设 Fabric 安装程序名为 fabric-installer.jar
        if not os.path.exists(fabric_installer_path):
            messagebox.showerror("错误", "指定的 Fabric 安装程序文件不存在")
            return

        log_message(f"启动 {server_type} 服务器: {fabric_installer_path}，分配内存: {memory}MB", is_launcher=True)
        try:
            # 检查 Java 路径是否存在
            if not os.path.exists(java_path):
                java_path = "javaw"  # 使用系统默认的 Java

            # 使用 javaw 启动 Fabric 服务器，并避免弹出窗口
            process = subprocess.Popen(
                [java_path, "-Xmx" + memory + "M", "-jar", fabric_installer_path, "server"],
                cwd=server_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW  # 确保没有弹窗
            )
            def read_output():
                for line in process.stdout:
                    log_message(line.strip(), is_launcher=True)
                for line in process.stderr:
                    log_message(line.strip(), is_launcher=True)

            threading.Thread(target=read_output, daemon=True).start()
            log_message(f"{server_type} 服务器启动成功", is_launcher=True)
        except Exception as e:
            error_message = f"启动 {server_type} 服务器失败: {e}"
            messagebox.showerror("错误", error_message)
            log_message(error_message, is_launcher=True)

    elif server_type == "forge":
        version = version_var.get()  # 获取用户选择的版本
        build_number = "36.2.42"  # 假设这是您要使用的构建号
        forge_jar_path = os.path.join(server_path, f"forge-{version}-{build_number}.jar")  # 构建 JAR 文件名
        if not os.path.exists(forge_jar_path):
            messagebox.showerror("错误", "指定的 Forge 启动文件不存在")
            return

        log_message(f"启动 {server_type} 服务器: {forge_jar_path}，分配内存: {memory}MB", is_launcher=True)
        try:
            # 检查 Java 路径是否存在
            if not os.path.exists(java_path):
                java_path = "javaw"  # 使用系统默认的 Java

            # 使用 javaw 启动 Forge 服务器，并避免弹出窗口
            process = subprocess.Popen(
                [java_path, "-Xmx" + memory + "M", "-jar", forge_jar_path],
                cwd=server_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW  # 确保没有弹窗
            )
            def read_output():
                for line in process.stdout:
                    log_message(line.strip(), is_launcher=True)
                for line in process.stderr:
                    log_message(line.strip(), is_launcher=True)

            threading.Thread(target=read_output, daemon=True).start()
            log_message(f"{server_type} 服务器启动成功", is_launcher=True)
        except Exception as e:
            error_message = f"启动 {server_type} 服务器失败: {e}"
            messagebox.showerror("错误", error_message)
            log_message(error_message, is_launcher=True)

# 加载配置
config = load_config()

root.mainloop()

# 保存配置
config["install_path"] = install_path_var.get()
config["launcher_path"] = launcher_path_var.get()  # 保存启动路径
save_config(config)