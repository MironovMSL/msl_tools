# ui/widgets/atoms/header/assistant_button.py
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class AssistantButton(qt.QtWidgets.QAbstractButton):
    """Header switch of an assistant's access: a robot's head that says how far it goes.

        off       grey, eyes shut (two lines)          no access
        on        lit, eyes open, a calm mouth,        it may look
                  a grey antenna
        + acting  its eyes glow, it grins, the         it may also act (run things)
                  antenna's ball is green, and the
                  whole head is a little bigger
        peers     a dot at the corner                  an assistant is connected right now
        working   it looks left and right, its         it is doing something this moment
                  antenna glows in time

    A change of on / off plays once: it wakes - opens its eyes, shakes its
    head, swells and settles while a ring spreads from it (switching off, it
    shuts its eyes and goes grey). The other changes glide into each other
    (GLIDE_MS): between "it may look" and "it may act" the mouth opens into
    the grin, the eyes and the antenna change color and the ball hops; the
    dot grows in and shrinks away. It only shows what it is told
    (set_state()); the owner decides what the states mean, sets the tooltip
    and handles the click and the right click (menu_requested). In the hub:
    the assistant's channel (run_hub.py).

    It is in color once awake - a top-lit head in the accent (the primary
    button's gradient), a light face, warm eyes and a green antenna ball when
    it may act - and all grey asleep; switching, every color runs from one
    look to the other. Colors are Qt properties set by ui/theme/widgets.qss:
    headTopColor, headBottomColor, faceColor, glowColor (the eyes),
    antennaColor, offColor, peerColor, hoverColor, pressedColor. The head stands in the button's middle in every
    state: "may act" is told by the FACE and the dot sits ON the head's corner
    like a badge - nothing beside it needs room, so nothing jumps and the
    hover tint lies evenly around it.
    """

    HEIGHT = 26
    WIDTH = 30
    SCALE = 1.15       # the drawing below is in a 14 x 11 head's units, shown this much bigger
    GROWN = 1.10       # ... and this much more once it may act: the bigger head has more say
    HEAD_W = 14.0      # the head
    HEAD_H = 11.0
    EYE = 1.5          # an open eye's radius
    PLAY_MS = 520
    GLIDE_MS = 360     # from one mood to the other; the dot growing in
    TURN_MS = 1600     # one look left and right while working

    menu_requested = qt.QtCore.Signal(qt.QtCore.QPoint)   # a right click, global position

    headTopColor = color_property("_head_top_color")
    headBottomColor = color_property("_head_bottom_color")
    faceColor = color_property("_face_color")
    glowColor = color_property("_glow_color")
    antennaColor = color_property("_antenna_color")
    offColor = color_property("_off_color")
    peerColor = color_property("_peer_color")
    hoverColor = color_property("_hover_color")
    pressedColor = color_property("_pressed_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._head_top_color = qt.QtGui.QColor(fallback.accent)
        self._head_bottom_color = qt.QtGui.QColor(fallback.accent)
        self._face_color = qt.QtGui.QColor("white")       # replaced by --on-accent once QSS applies
        self._glow_color = qt.QtGui.QColor(fallback.warning)
        self._antenna_color = qt.QtGui.QColor(fallback.success)
        self._off_color = qt.QtGui.QColor(fallback.text_secondary)
        self._peer_color = qt.QtGui.QColor(fallback.success)
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._pressed_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._on = False
        self._acting = False
        self._peers = 0
        self._working = False
        self._told = False     # set_state() was called once: later changes of on / off play
        self._hovered = False
        self._play = 1.0       # 0..1 through the switch animation; 1 = at rest
        self._turn = 0.0       # 0..1 through one round (working only)

        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._play_animation = qt.QtCore.QVariantAnimation(self)
        self._play_animation.setStartValue(0.0)
        self._play_animation.setEndValue(1.0)
        self._play_animation.setDuration(self.PLAY_MS)
        self._play_animation.valueChanged.connect(self._on_play)
        self._turn_animation = qt.QtCore.QVariantAnimation(self)
        self._turn_animation.setStartValue(0.0)
        self._turn_animation.setEndValue(1.0)
        self._turn_animation.setDuration(self.TURN_MS)
        self._turn_animation.setLoopCount(-1)
        self._turn_animation.valueChanged.connect(self._on_turn)
        # How much of "may act" (the mood) and of "someone is connected" (the dot) is shown:
        # each glides to its new value, so no state snaps into another.
        self._mood = 0.0
        self._mood_animation = self._glider(self._on_mood)
        self._peer = 0.0
        self._peer_animation = self._glider(self._on_peer)

    def _glider(self, slot) -> qt.QtCore.QVariantAnimation:
        animation = qt.QtCore.QVariantAnimation(self)
        animation.setDuration(self.GLIDE_MS)
        animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(slot)
        return animation

    def _glide(self, animation, current: float, target: float, slot) -> None:
        """`animation` takes its value from `current` to `target` (at once while not on screen)."""
        animation.stop()
        if current == target:
            return
        if not (self._told and self.isVisible()):
            slot(target)
            return
        animation.setStartValue(float(current))
        animation.setEndValue(float(target))
        animation.start()

    def _on_mood(self, value) -> None:
        self._mood = float(value)
        self.update()

    def _on_peer(self, value) -> None:
        self._peer = float(value)
        self.update()

    # --- state -------------------------------------------------------------------

    def set_state(self, on: bool, acting: bool = False, peers: int = 0, working: bool = False) -> None:
        """What to show (see the class docstring). After the first call every change is
        animated: on / off plays the waking, the others glide into each other."""
        state = (bool(on), bool(acting), max(int(peers), 0), bool(working))
        if state == (self._on, self._acting, self._peers, self._working) and self._told:
            return
        switched = self._told and state[0] != self._on
        self._glide(self._mood_animation, self._mood, 1.0 if state[1] else 0.0, self._on_mood)
        self._glide(self._peer_animation, self._peer, 1.0 if state[2] and state[0] else 0.0, self._on_peer)
        self._on, self._acting, self._peers, self._working = state
        self._told = True
        if switched:
            self.play()
        self._sync_turn()
        self.update()

    def is_on(self) -> bool:
        return self._on

    def play(self) -> None:
        """Plays the switch animation once (towards the state shown now)."""
        self._play_animation.stop()
        if self.isVisible():
            self._play_animation.start()
        else:
            self._play = 1.0

    def _on_play(self, value) -> None:
        self._play = float(value)
        self.update()

    def _on_turn(self, value) -> None:
        self._turn = float(value)
        self.update()

    def _sync_turn(self) -> None:
        wanted = self._working and self._on and self.isVisible()
        running = self._turn_animation.state() == qt.QtCore.QAbstractAnimation.State.Running
        if wanted and not running:
            self._turn_animation.start()
        elif not wanted and running:
            self._turn_animation.stop()
            self._turn = 0.0

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_turn()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._play_animation.stop()
        self._play = 1.0
        for animation in (self._mood_animation, self._peer_animation):   # off screen: where they were going
            if animation.state() == qt.QtCore.QAbstractAnimation.State.Running:
                animation.setCurrentTime(animation.duration())
                animation.stop()
        self._sync_turn()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    # --- painting ------------------------------------------------------------------

    @staticmethod
    def _mix(first, second, amount: float) -> qt.QtGui.QColor:
        """`first` at 0, `second` at 1, evenly between."""
        amount = min(max(amount, 0.0), 1.0)
        return qt.QtGui.QColor.fromRgbF(*(a + (b - a) * amount for a, b in zip(first.getRgbF(), second.getRgbF())))

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect())

        if self.isDown() or self._hovered:
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._pressed_color if self.isDown() else self._hover_color)
            painter.drawRoundedRect(rect.adjusted(0, 1, 0, -1), 6, 6)   # holds the antenna too

        playing = self._play < 1.0
        eased = 1.0 - (1.0 - self._play) ** 3                      # fast, then settling
        swell = 1.0 + 0.16 * math.sin(math.pi * self._play) if playing else 1.0
        # It shakes its head once as it wakes (or dozes off): a tilt that dies away.
        tilt = 16.0 * math.sin(2.0 * math.pi * self._play) * (1.0 - self._play) if playing else 0.0
        # How awake it is: it wakes while switching on, dozes off while switching off.
        awake = (eased if self._on else 1.0 - eased) if playing else (1.0 if self._on else 0.0)

        # The head stands in ONE place whatever state is shown.
        center = qt.QtCore.QPointF(rect.center().x(), rect.center().y() + 2.5)
        edge = self._mix(self._off_color, self._head_bottom_color, awake)      # outline, ears, stalk
        face = self._mix(self._off_color, self._face_color, awake)             # eyes, mouth
        mood = self._mood                                                      # 0 = it only looks, 1 = it may act
        # The antenna's ball: grey while it only looks, in the antenna color once it may act.
        ball = self._mix(self._off_color, self._antenna_color, awake * mood)
        # How far through a change of mood: the ball hops once on the way.
        hop = math.sin(math.pi * mood) if 0.0 < mood < 1.0 else 0.0
        # It is a little bigger once it may act - growing with the mood, and only while awake.
        size = self.SCALE * (1.0 + (self.GROWN - 1.0) * mood * awake)
        pen = qt.QtGui.QPen(edge, 1.3, qt.QtCore.Qt.PenStyle.SolidLine, qt.QtCore.Qt.PenCapStyle.RoundCap,
                            qt.QtCore.Qt.PenJoinStyle.RoundJoin)

        if playing and self._on:
            ring = qt.QtGui.QColor(self._head_top_color)
            ring.setAlphaF(0.55 * (1.0 - self._play))
            painter.setPen(qt.QtGui.QPen(ring, 1.3))
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            spread = self.HEAD_W * size * (0.42 + 0.26 * eased)   # stays inside the button
            painter.drawEllipse(qt.QtCore.QPointF(center.x(), center.y() - 1.0), spread, spread)

        painter.save()
        painter.translate(center)
        painter.rotate(tilt)
        painter.scale(swell * size, swell * size)
        half_w, half_h = self.HEAD_W / 2.0, self.HEAD_H / 2.0
        # The antenna: a stalk and a ball, which glows in time while it works.
        beat = 0.5 + 0.5 * math.sin(2.0 * math.pi * self._turn * 2.0) if self._working and self._on else 0.0
        painter.setPen(pen)
        painter.drawLine(qt.QtCore.QPointF(0.0, -half_h), qt.QtCore.QPointF(0.0, -half_h - 2.4))
        top = qt.QtCore.QPointF(0.0, -half_h - 3.6 - 0.8 * hop)
        if beat > 0.0:
            halo = qt.QtGui.QColor(self._antenna_color)
            halo.setAlphaF(0.35 * beat)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(top, 3.4, 3.4)
        painter.setPen(qt.QtGui.QPen(ball, 1.2))
        painter.setBrush(ball if awake > 0.5 else qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(top, 1.4 + 0.5 * hop, 1.4 + 0.5 * hop)
        # The ears.
        painter.setPen(qt.QtGui.QPen(edge, 2.0, qt.QtCore.Qt.PenStyle.SolidLine, qt.QtCore.Qt.PenCapStyle.RoundCap))
        painter.drawLine(qt.QtCore.QPointF(-half_w - 1.5, -1.0), qt.QtCore.QPointF(-half_w - 1.5, 1.6))
        painter.drawLine(qt.QtCore.QPointF(half_w + 1.5, -1.0), qt.QtCore.QPointF(half_w + 1.5, 1.6))
        # The head: top-lit like a primary button once it is awake, an empty outline asleep.
        head = qt.QtCore.QRectF(-half_w, -half_h, self.HEAD_W, self.HEAD_H)
        shade = qt.QtGui.QLinearGradient(head.topLeft(), head.bottomLeft())
        for stop, tone in ((0.0, self._head_top_color), (1.0, self._head_bottom_color)):
            tone = qt.QtGui.QColor(tone)
            tone.setAlphaF(tone.alphaF() * awake)
            shade.setColorAt(stop, tone)
        painter.setPen(pen)
        painter.setBrush(shade)
        painter.drawRoundedRect(head, 3.2, 3.2)
        # The eyes: lines while it sleeps, dots when awake; they look left and right while it works.
        look = 1.1 * math.sin(2.0 * math.pi * self._turn) if self._working and self._on else 0.0
        # Allowed to act, its eyes light up in the glow color (and it smiles, below).
        eyes = self._mix(face, self._mix(self._off_color, self._glow_color, awake), mood)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(eyes)
        eye_h = max(0.45, self.EYE * awake)
        for side in (-1.0, 1.0):
            painter.drawEllipse(qt.QtCore.QPointF(side * 3.1 + look, -0.9), self.EYE, eye_h)
        # The mouth, once it is awake.
        if awake > 0.05:
            mouth = qt.QtGui.QColor(face)
            mouth.setAlphaF(face.alphaF() * awake)
            painter.setPen(qt.QtGui.QPen(mouth, 1.2, qt.QtCore.Qt.PenStyle.SolidLine,
                                         qt.QtCore.Qt.PenCapStyle.RoundCap))
            # One shape for both moods: a straight line that OPENS into a grin (a flat top, a
            # round bottom, filled) as it comes to "may act" - so the mouth can pass between them.
            reach = (2.0 + 1.1 * mood) * awake
            top_y = 2.7 - 1.0 * mood
            grin = qt.QtGui.QPainterPath(qt.QtCore.QPointF(-reach, top_y))
            grin.lineTo(qt.QtCore.QPointF(reach, top_y))
            grin.quadTo(qt.QtCore.QPointF(0.0, top_y + 5.2 * mood * awake), qt.QtCore.QPointF(-reach, top_y))
            inside = qt.QtGui.QColor(mouth)
            inside.setAlphaF(mouth.alphaF() * mood)
            painter.setBrush(inside)
            painter.drawPath(grin)
        painter.restore()

        if self._peer > 0.0:   # it grows in, and shrinks away
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._peer_color)
            dot = 2.4 * self._peer * (1.0 + 0.35 * math.sin(math.pi * self._peer))
            corner = qt.QtCore.QPointF(center.x() + (half_w + 0.6) * size, center.y() + (half_h - 0.6) * size)
            painter.drawEllipse(corner, dot, dot)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for label, state in (("off", (False,)), ("on", (True,)), ("on, may act", (True, True)),
                             ("off, would act", (False, True)), ("an assistant connected", (True, True, 1)),
                             ("working", (True, True, 1, True))):
            button = AssistantButton()
            button.set_state(*state)
            button.clicked.connect(lambda _checked=False, b=button: b.set_state(not b.is_on(), b._acting, b._peers))
            dialog.add_case(label + " (click)", button)
        dialog.show()
