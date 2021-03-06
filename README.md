<!--
 * @Author        : fineemb
 * @Github        : https://github.com/fineemb
 * @Description   : 
 * @Date          : 2020-08-26 16:20:12
 * @LastEditors   : fineemb
 * @LastEditTime  : 2021-03-06 11:01:18
-->

# 小米云服务

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

小米云服务, 支持一个账号下的多设备
提供`device_tracker`用来定位设备
可以提供锁机, 响铃, 云剪贴板这些服务

## 更新

+ ### v1.0
  + 支持多设备
  + 设备查找
+ ### v1.1
  + 增加坐标类型选择
  + 增加位置刷新频率设置,单位为分钟(过高的频率会导致手机耗电严重)

+ ### v1.2
  + 增加设备发声服务
  + 增加设备丢失模式
  + 增加云剪贴板
  
+ ### v1.2.1
  + 修复数据不更新的问题

+ ### v1.2.2
  + 小米不在提供`original`坐标格式, 默认改为`baidu`坐标
  
+ ### v1.2.3
  + `original`坐标格式回归

+ ### v1.2.4
  + 修复无法登录的问题
  + 设置默认扫描间隔为60分钟 #5
    某些情况下特别是双卡用户小米会启用短信验证,导致意外的费用.所以加大默认扫描间隔, 过于频繁的请求位置也会增加电耗.
+ ### v1.2.5
  + 修复配置页面无法登录的问题
  + manifest.json增加版本号

## 安装配置

建议使用HACS安装,在配置-集成里面添加和设置

## 服务

### `xiaomi_cloud.clipboard`
云剪贴板

| 服务属性 | 选项 | 描述|
|---------|------|----|
|`text`   | 必须 | 发送到剪贴板的文本内容|

### `xiaomi_cloud.find`
查找设备

| 服务属性 | 选项 | 描述|
|---------|------|----|
|`imei`   | 必须 | 设备的imei号,请在集成的`device_tracker`属性里查找|

### `xiaomi_cloud.noise`
设备发声

| 服务属性 | 选项 | 描述|
|---------|------|----|
|`imei`   | 必须 | 设备的imei号,请在集成的`device_tracker`属性里查找|

### `xiaomi_cloud.lost`
开启丢失模式

| 服务属性 | 选项 | 描述|
|---------|------|----|
|`imei`   | 必须 | 设备的imei号,请在集成的`device_tracker`属性里查找|
|`content`   | 必须 | 锁定设备屏幕上显示的留言|
|`phone`   | 必须 | 锁定设备屏幕上显示的手机号码|
|`onlinenotify`   | 必须 | 定位到丢失设备时，是否短信通知上面号码|

