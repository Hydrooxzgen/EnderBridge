using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace EnderBridge.App.Services;

public class EnderBridgeApiClient
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(5) };
    private string _baseUrl = "http://127.0.0.1:18888";

    public EnderBridgeApiClient()
    {
        _http.DefaultRequestHeaders.Add("X-EB-GUI", "1");
        _http.DefaultRequestHeaders.Add("X-Auth-Guest", "1");
    }

    public void SetBaseUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        _baseUrl = url.TrimEnd('/');
    }

    private string? _token;

    public string? Token => _token;

    public void SetToken(string? token)
    {
        _token = token;
        _http.DefaultRequestHeaders.Remove("X-Auth-Token");
        _http.DefaultRequestHeaders.Remove("X-Auth-Guest");
        if (!string.IsNullOrEmpty(token))
        {
            _http.DefaultRequestHeaders.Add("X-Auth-Token", token);
        }
        else
        {
            _http.DefaultRequestHeaders.Add("X-Auth-Guest", "1");
        }
    }

    public async Task<(bool ok, string message, string? token, string? username, string? role)> LoginAsync(string username, string password)
    {
        try
        {
            var body = JsonSerializer.Serialize(new { username, password });
            var resp = await _http.PostAsync($"{_baseUrl}/api/auth", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? "登录成功" : "登录失败");
            var token = node?["token"]?.GetValue<string>();
            var role = node?["role"]?.GetValue<string>();
            var uname = node?["username"]?.GetValue<string>() ?? username;

            if (ok && !string.IsNullOrEmpty(token))
            {
                SetToken(token);
            }
            return (ok, msg, token, uname, role);
        }
        catch (Exception ex)
        {
            return (false, ex.Message, null, null, null);
        }
    }

    public async Task<bool> LogoutAsync()
    {
        try
        {
            await _http.PostAsync($"{_baseUrl}/api/auth/logout", new StringContent("{}", Encoding.UTF8, "application/json"));
        }
        catch {}
        SetToken(null);
        return true;
    }

    public async Task<JsonNode?> GetMeAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_baseUrl}/api/auth/me");
            return JsonNode.Parse(res);
        }
        catch
        {
            return null;
        }
    }

    // 1. 模组列表
    public async Task<JsonNode?> GetModsAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_baseUrl}/api/mods");
            return JsonNode.Parse(res);
        }
        catch
        {
            return null;
        }
    }

    // 2. 热重载所有模组
    public async Task<(bool ok, string message)> ReloadAllModsAsync()
    {
        try
        {
            var resp = await _http.PostAsync($"{_baseUrl}/api/mods/reload-all", new StringContent("{}", Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? "所有模组重载成功" : "重载失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    // 3. 重载单个模组
    public async Task<(bool ok, string message)> ReloadModAsync(string name, string target = "server")
    {
        try
        {
            var body = JsonSerializer.Serialize(new { name, target });
            var resp = await _http.PostAsync($"{_baseUrl}/api/mods/reload", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? $"模组 {name} 重载成功" : "重载失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    // 3.1 启用 / 禁用模组 (POST /api/mods/toggle)
    public async Task<(bool ok, string message)> ToggleModAsync(string name, string side, bool enabled)
    {
        try
        {
            var body = JsonSerializer.Serialize(new { name, side, enabled });
            var resp = await _http.PostAsync($"{_baseUrl}/api/mods/toggle", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? $"模组 {name} 状态已更新" : "更新失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    // 4. 获取配置
    public async Task<JsonNode?> GetConfigAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_baseUrl}/api/config");
            return JsonNode.Parse(res);
        }
        catch
        {
            return null;
        }
    }

    // 5. 保存配置
    public async Task<(bool ok, string message)> SaveConfigAsync(JsonNode configObject)
    {
        try
        {
            var reqObj = new JsonObject
            {
                ["config"] = configObject.DeepClone()
            };
            var body = reqObj.ToJsonString();
            var request = new HttpRequestMessage(HttpMethod.Put, $"{_baseUrl}/api/config")
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json")
            };
            var resp = await _http.SendAsync(request);
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? "配置已成功保存并应用！" : "保存配置失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    // 6. 获取工坊资产
    public async Task<JsonNode?> GetStudioAssetsAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_baseUrl}/api/studio/assets");
            return JsonNode.Parse(res);
        }
        catch
        {
            return null;
        }
    }

    // 7. 获取快照备份
    public async Task<JsonNode?> GetBackupsAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_baseUrl}/api/backups");
            return JsonNode.Parse(res);
        }
        catch
        {
            return null;
        }
    }

    // 8. 创建快照备份
    public async Task<(bool ok, string message)> CreateBackupAsync(string desc = "GUI 一键手动备份")
    {
        try
        {
            var body = JsonSerializer.Serialize(new { description = desc });
            var resp = await _http.PostAsync($"{_baseUrl}/api/backups", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? "备份创建成功" : "备份创建失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    // 10. 触发服务端在线安全更新与重启 (POST /api/update/install)
    public async Task<(bool ok, string message)> InstallUpdateAsync(string githubTag)
    {
        try
        {
            var body = JsonSerializer.Serialize(new { github_tag = githubTag });
            var resp = await _http.PostAsync($"{_baseUrl}/api/update/install", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await resp.Content.ReadAsStringAsync();
            var node = JsonNode.Parse(text);
            var ok = node?["ok"]?.GetValue<bool>() ?? resp.IsSuccessStatusCode;
            var msg = node?["message"]?.GetValue<string>() ?? (ok ? "服务器正在更新..." : "更新失败");
            return (ok, msg);
        }
        catch (Exception ex)
        {
            return (false, $"请求失败: {ex.Message}");
        }
    }
}
