import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: generalPage
    readonly property var theme: Theme.palette(uiState.darkMode)

    // Reactive shortcut — all s["key"] bindings update when lm.languageChanged fires
    property var s: lm.strings

    function updateStatusText() {
        if (backend.updateInstallStatus === "checking")
            return s["scroll.update_checking"]
        if (backend.updateInstallStatus === "downloading")
            return s["scroll.update_downloading"]
        if (backend.updateInstallStatus === "verifying")
            return s["scroll.update_verifying"]
        if (backend.updateInstallStatus === "ready_to_install")
            return s["scroll.update_ready"]
        if (backend.updateInstallStatus === "installing")
            return s["scroll.update_installing"]
        if (backend.updateInstallStatus === "installed")
            return backend.updateInstallMessage ? s["scroll.update_installed_version"].replace("%1", backend.updateInstallMessage) : s["scroll.update_installed"]
        if (backend.updateInstallStatus === "cancelled")
            return s["scroll.update_cancelled"]
        if (backend.updateInstallStatus === "manual_fallback") {
            if (backend.updateInstallMessage === "macos")
                return s["scroll.update_manual_macos"]
            if (backend.updateInstallMessage === "linux")
                return s["scroll.update_manual_linux"]
            if (backend.updateInstallMessage === "windows")
                return s["scroll.update_manual_windows"]
            if (backend.updateInstallMessage === "no_asset")
                return s["scroll.update_no_asset"]
            return s["scroll.update_manual"]
        }
        if (backend.updateInstallStatus === "error") {
            var key = "scroll.update_error_" + backend.updateInstallMessage
            if (s[key])
                return s[key]
            return s["scroll.update_error"]
        }
        if (backend.latestUpdateVersion)
            return s["scroll.update_available"].replace("%1", backend.latestUpdateVersion)
        return s["scroll.update_idle"]
    }

    readonly property var appearanceOptions: [
        { label: s["scroll.system"], value: "system" },
        { label: s["scroll.light"],  value: "light"  },
        { label: s["scroll.dark"],   value: "dark"   }
    ]
    readonly property var allDpiPresets: [400, 800, 1000, 1600, 2400, 4000, 6000, 8000]
    readonly property var dpiPresets: {
        var presets = []
        for (var i = 0; i < allDpiPresets.length; i++) {
            var preset = allDpiPresets[i]
            if (preset >= backend.deviceDpiMin && preset <= backend.deviceDpiMax)
                presets.push(preset)
        }
        return presets
    }

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        Column {
            id: mainCol
            width: pageScroll.availableWidth
            spacing: 0

            Item {
                width: parent.width
                height: 96

                Column {
                    anchors {
                        left: parent.left
                        leftMargin: 36
                        verticalCenter: parent.verticalCenter
                    }
                    spacing: 4

                    Text {
                        text: s["general.title"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 24
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: s["general.subtitle"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 13
                        }
                        color: generalPage.theme.textSecondary
                    }
                }
            }

            Rectangle {
                width: parent.width - 72
                height: 1
                color: generalPage.theme.border
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 24 }

            // ── DPI / Pointer Speed ───────────────────────────────
            Rectangle {
                id: dpiCard
                visible: backend.hidFeaturesReady
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: dpiContent.implicitHeight + 40
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Column {
                    id: dpiContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.pointer_speed"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: backend.deviceDpiMin === 200 && backend.deviceDpiMax === 8000
                              ? s["scroll.pointer_speed_desc"]
                              : s["scroll.pointer_speed_desc_range_prefix"]
                                + backend.deviceDpiMin
                                + s["scroll.pointer_speed_desc_range_to"]
                                + backend.deviceDpiMax
                                + s["scroll.pointer_speed_desc_range_suffix"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textSecondary
                    }

                    RowLayout {
                        width: parent.width
                        spacing: 12

                        Text {
                            text: backend.deviceDpiMin
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: generalPage.theme.textDim
                        }

                        WheelSafeSlider {
                            id: dpiSlider
                            Layout.fillWidth: true
                            from: backend.deviceDpiMin
                            to: backend.deviceDpiMax
                            stepSize: 50
                            value: backend.dpi
                            accentColor: generalPage.theme.accent
                            accentDimColor: generalPage.theme.accentDim
                            trackColor: generalPage.theme.border

                            onMoved: {
                                dpiLabel.text = Math.round(value) + " DPI"
                                dpiDebounce.restart()
                            }
                        }

                        Text {
                            text: backend.deviceDpiMax
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: generalPage.theme.textDim
                        }

                        Rectangle {
                            Layout.preferredWidth: 104
                            Layout.preferredHeight: 36
                            radius: 10
                            color: generalPage.theme.accentDim

                            Text {
                                id: dpiLabel
                                anchors.centerIn: parent
                                text: backend.dpi + " DPI"
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 14
                                    bold: true
                                }
                                color: generalPage.theme.accent
                            }
                        }
                    }

                    Timer {
                        id: dpiDebounce
                        interval: 400
                        onTriggered: backend.setDpi(Math.round(dpiSlider.value))
                    }

                    Flow {
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.presets"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: generalPage.theme.textDim
                        }

                        Repeater {
                            model: generalPage.dpiPresets

                            delegate: Rectangle {
                                width: presetText.implicitWidth + 20
                                height: 30
                                radius: 8
                                color: dpiSlider.value === modelData
                                       ? generalPage.theme.accent
                                       : presetMouse.containsMouse
                                         ? generalPage.theme.bgCardHover
                                         : generalPage.theme.bgSubtle
                                border.width: 1
                                border.color: generalPage.theme.border

                                Accessible.role: Accessible.Button
                                Accessible.name: modelData + " DPI"

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: presetText
                                    anchors.centerIn: parent
                                    text: modelData
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: dpiSlider.value === modelData
                                           ? generalPage.theme.bgSidebar
                                           : generalPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: presetMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        dpiSlider.value = modelData
                                        dpiLabel.text = modelData + " DPI"
                                        backend.setDpi(modelData)
                                    }
                                }
                            }
                        }
                    }
                }
            }


            Item { width: 1; height: 16 }

            // ── Appearance ────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: appearanceContent.implicitHeight + 40
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Column {
                    id: appearanceContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.appearance"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.appearance_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textSecondary
                    }

                    Row {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: generalPage.appearanceOptions

                            delegate: Rectangle {
                                required property var modelData
                                width: Math.max(96, optionText.implicitWidth + 28)
                                height: 38
                                radius: 10
                                color: backend.appearanceMode === modelData.value
                                       ? generalPage.theme.accent
                                       : optionMouse.containsMouse
                                         ? generalPage.theme.bgCardHover
                                         : generalPage.theme.bgSubtle
                                border.width: 1
                                border.color: backend.appearanceMode === modelData.value
                                              ? generalPage.theme.accent
                                              : generalPage.theme.border

                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.label

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Text {
                                    id: optionText
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: backend.appearanceMode === modelData.value
                                    }
                                    color: backend.appearanceMode === modelData.value
                                           ? generalPage.theme.bgSidebar
                                           : generalPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: optionMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setAppearanceMode(modelData.value)
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Language ──────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: languageContent.implicitHeight + 40
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Column {
                    id: languageContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.language"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.language_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textSecondary
                    }

                    Row {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: lm.availableLanguages

                            delegate: Rectangle {
                                required property var modelData
                                width: Math.max(108, langText.implicitWidth + 28)
                                height: 38
                                radius: 10
                                color: lm.language === modelData.code
                                       ? generalPage.theme.accent
                                       : langMa.containsMouse
                                         ? generalPage.theme.bgCardHover
                                         : generalPage.theme.bgSubtle
                                border.width: 1
                                border.color: lm.language === modelData.code
                                              ? generalPage.theme.accent
                                              : generalPage.theme.border

                                Behavior on color { ColorAnimation { duration: 120 } }

                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.name
                                Accessible.checkable: true
                                Accessible.checked: lm.language === modelData.code
                                Accessible.onPressAction: lm.setLanguage(modelData.code)

                                Text {
                                    id: langText
                                    anchors.centerIn: parent
                                    text: modelData.name
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: lm.language === modelData.code
                                    }
                                    color: lm.language === modelData.code
                                           ? generalPage.theme.bgSidebar
                                           : generalPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: langMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: lm.setLanguage(modelData.code)
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Startup ───────────────────────────────────────────
            Rectangle {
                visible: backend.supportsStartAtLogin
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: startupContent.implicitHeight + 40
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Column {
                    id: startupContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.startup"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.startup_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: generalPage.theme.bgSubtle
                        visible: backend.supportsStartAtLogin

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: s["scroll.start_at_login"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: generalPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startAtLoginSwitch
                                checked: backend.startAtLogin
                                focusPolicy: Qt.StrongFocus
                                Material.accent: generalPage.theme.accent
                                Accessible.name: s["scroll.start_at_login"]
                                onClicked: backend.setStartAtLogin(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: generalPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: s["scroll.start_minimized"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: generalPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: startMinimizedSwitch
                                checked: backend.startMinimized
                                focusPolicy: Qt.StrongFocus
                                Material.accent: generalPage.theme.accent
                                Accessible.name: s["scroll.start_minimized"]
                                onClicked: backend.setStartMinimized(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 118
                        radius: 10
                        color: generalPage.theme.bgSubtle

                        ColumnLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                                topMargin: 10
                                bottomMargin: 10
                            }
                            spacing: 12

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                Column {
                                    Layout.fillWidth: true
                                    spacing: 3

                                    Text {
                                        text: s["scroll.check_for_updates"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: generalPage.theme.textPrimary
                                    }

                                    Text {
                                        width: parent.width
                                        text: s["scroll.check_for_updates_desc"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 11
                                        }
                                        color: generalPage.theme.textSecondary
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                Switch {
                                    id: checkUpdatesSwitch
                                    checked: backend.checkForUpdates
                                    focusPolicy: Qt.StrongFocus
                                    Material.accent: generalPage.theme.accent
                                    Accessible.name: s["scroll.check_for_updates"]
                                    onClicked: backend.setCheckForUpdates(checked)
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: generalPage.updateStatusText()
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: generalPage.theme.textSecondary
                                    elide: Text.ElideRight
                                }

                                ProgressBar {
                                    Layout.preferredWidth: 120
                                    visible: backend.updateInstallStatus === "downloading"
                                    from: 0
                                    to: 100
                                    value: backend.updateInstallProgress
                                }

                                Button {
                                    text: s["scroll.update_check"]
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.manualCheckForUpdates()
                                }

                                Button {
                                    text: backend.isWindows ? s["scroll.update_download"] : s["scroll.update_verify"]
                                    visible: backend.latestUpdateVersion !== ""
                                             && !backend.updateInstallCanInstall
                                             && (!backend.isWindows || backend.updateInstallEnabled)
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.prepareLatestUpdate()
                                }

                                Button {
                                    text: s["scroll.update_cancel"]
                                    visible: backend.updateInstallStatus === "checking"
                                             || backend.updateInstallStatus === "downloading"
                                             || backend.updateInstallStatus === "verifying"
                                    onClicked: backend.cancelUpdatePreparation()
                                }

                                Button {
                                    text: s["scroll.update_install"]
                                    visible: backend.updateInstallCanInstall && backend.updateInstallEnabled
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.installPreparedUpdate()
                                }

                                Button {
                                    text: s["scroll.update_open_release"]
                                    visible: backend.latestUpdateVersion !== ""
                                    enabled: !backend.updateInstallInProgress
                                    onClicked: backend.openLatestReleasePage()
                                }
                            }
                        }
                    }
                }
            }

            Item {
                width: 1
                height: backend.supportsStartAtLogin ? 16 : 0
            }

            // ── Screenshots ───────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: screenshotContent.implicitHeight + 40
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Column {
                    id: screenshotContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 12

                    Text {
                        text: s["scroll.screenshots"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: generalPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.screenshots_desc"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textSecondary
                        wrapMode: Text.WordWrap
                        width: parent.width
                    }

                    Rectangle {
                        width: parent.width
                        height: 58
                        radius: 10
                        color: generalPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 12
                            }
                            spacing: 10

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: s["scroll.screenshots_save_to"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                        bold: true
                                    }
                                    color: generalPage.theme.textDim
                                }

                                Text {
                                    text: backend.hasCustomScreenshotDirectory
                                          ? backend.screenshotDirectoryLabel
                                          : s["scroll.screenshots_system_default"]
                                    width: parent.width
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 13
                                    }
                                    color: generalPage.theme.textPrimary
                                    elide: Text.ElideMiddle
                                }
                            }

                            Rectangle {
                                id: chooseScreenshotButton
                                Layout.preferredWidth: Math.max(88, chooseScreenshotText.implicitWidth + 24)
                                Layout.preferredHeight: 34
                                radius: 8
                                color: chooseScreenshotMouse.containsMouse
                                       ? generalPage.theme.bgCardHover
                                       : generalPage.theme.bgCard
                                border.width: 1
                                border.color: generalPage.theme.border

                                Text {
                                    id: chooseScreenshotText
                                    anchors.centerIn: parent
                                    text: s["scroll.screenshots_choose"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: generalPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: chooseScreenshotMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.chooseScreenshotDirectory()
                                }
                            }

                            Rectangle {
                                id: resetScreenshotButton
                                Layout.preferredWidth: Math.max(102, resetScreenshotText.implicitWidth + 24)
                                Layout.preferredHeight: 34
                                radius: 8
                                opacity: backend.hasCustomScreenshotDirectory ? 1.0 : 0.45
                                color: resetScreenshotMouse.containsMouse && backend.hasCustomScreenshotDirectory
                                       ? generalPage.theme.bgCardHover
                                       : generalPage.theme.bgCard
                                border.width: 1
                                border.color: generalPage.theme.border

                                Text {
                                    id: resetScreenshotText
                                    anchors.centerIn: parent
                                    text: s["scroll.screenshots_default"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 12
                                    }
                                    color: generalPage.theme.textPrimary
                                }

                                MouseArea {
                                    id: resetScreenshotMouse
                                    anchors.fill: parent
                                    enabled: backend.hasCustomScreenshotDirectory
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.resetScreenshotDirectory()
                                }
                            }
                        }
                    }
                }
            }


            Item { width: 1; height: 16 }

            // ── DPI note ──────────────────────────────────────────
            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: noteRow.implicitHeight + 28
                radius: Theme.radius
                color: generalPage.theme.bgCard
                border.width: 1
                border.color: generalPage.theme.border

                Row {
                    id: noteRow
                    anchors {
                        fill: parent
                        margins: 14
                    }
                    spacing: 10

                    AppIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18
                        height: 18
                        name: "warning"
                        iconColor: generalPage.theme.warning
                    }

                    Text {
                        width: parent.width - 28
                        text: s["scroll.dpi_note"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: generalPage.theme.textDim
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Item { width: 1; height: 24 }
        }
    }

    Connections {
        target: backend
        function onDpiFromDevice(dpi) {
            if (!dpiSlider.pressed) {
                dpiSlider.value = dpi
                dpiLabel.text = dpi + " DPI"
            }
        }
        function onSettingsChanged() {
            if (!dpiSlider.pressed) {
                dpiSlider.value = backend.dpi
                dpiLabel.text = backend.dpi + " DPI"
            }
            if (backend.supportsStartAtLogin) {
                startAtLoginSwitch.checked = backend.startAtLogin
                startMinimizedSwitch.checked = backend.startMinimized
            }
            checkUpdatesSwitch.checked = backend.checkForUpdates
        }
    }
}
