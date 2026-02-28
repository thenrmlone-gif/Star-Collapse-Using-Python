import os
import sys
import ctypes
import math
from panda3d.core import loadPrcFileData, Point3, Vec4, Shader, OmniBoundingVolume, TextNode
from direct.showbase.ShowBase import ShowBase
from direct.interval.IntervalGlobal import Sequence, Parallel, LerpFunc, Wait, Func
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectSlider import DirectSlider
from direct.gui.DirectGui import DGG

# ==========================================
# 0. ENGINE CONFIGURATION 
# ==========================================
if os.name == 'nt':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

loadPrcFileData("", "gl-version 3 3")
loadPrcFileData("", "sync-video false")
loadPrcFileData("", "window-title Stellar Collapse")

# ==========================================
# 1. UNIFIED GLSL MASTER SHADER
# ==========================================
VERT_SHADER = """
#version 330
in vec4 p3d_Vertex;
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
out vec3 world_pos;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    world_pos = (p3d_ModelMatrix * p3d_Vertex).xyz;
}
"""

FRAG_SHADER = """
#version 330
in vec3 world_pos;
uniform vec3 camera_pos;
uniform float iTime;

// Master Physics States
uniform float star_radius;
uniform float star_temp; 

uniform float remnant_type; // 1.0=WD, 2.0=NS, 3.0=BH
uniform float remnant_mass; 
uniform float remnant_radius; 

uniform float explosion_type; // 1.0=Nebula
uniform float ejecta_radius;
uniform float ejecta_intensity;
uniform float flash_intensity;

uniform float disk_alpha;

out vec4 fragColor;
#define ITERATIONS 350

// --- 3D Noise Suite ---
float hash(float n) { return fract(sin(n) * 1e4); }
float noise(vec3 x) {
    vec3 i = floor(x); vec3 f = fract(x); f = f*f*(3.0-2.0*f);
    float n = i.x + i.y*157.0 + 113.0*i.z;
    return mix(mix(mix(hash(n+0.0), hash(n+1.0),f.x), mix(hash(n+157.0), hash(n+158.0),f.x),f.y),
               mix(mix(hash(n+113.0), hash(n+114.0),f.x), mix(hash(n+270.0), hash(n+271.0),f.x),f.y),f.z);
}
float fbm(vec3 p) {
    float f = 0.0; f += 0.5000*noise(p); p*=2.02; f += 0.2500*noise(p); p*=2.03; f += 0.1250*noise(p); return max(0.0, f);
}

vec3 ACESFilm(vec3 x) {
    float a = 2.51f; float b = 0.03f; float c = 2.43f; float d = 0.59f; float e = 0.14f;
    return clamp((x*(a*x+b))/(x*(c*x+d)+e), 0.0, 1.0);
}

vec3 stellarColor(float temp) {
    float t = clamp((temp - 3000.0) / 57000.0, 0.0, 1.0); 
    
    vec3 class_M = vec3(1.0, 0.2, 0.05); // 3000K (Red)
    vec3 class_G = vec3(1.0, 0.9, 0.7);  // 6000K (Yellow/White)
    vec3 class_A = vec3(1.0, 1.0, 1.0);  // 10000K (Pure White)
    vec3 class_B = vec3(0.6, 0.8, 1.0);  // 20000K (Blue/White)
    vec3 class_O = vec3(0.2, 0.5, 1.0);  // 40000K (Deep Blue)
    vec3 class_WR= vec3(0.3, 0.1, 1.0);  // 60000K+ (Deep Violet-Blue)
    
    if (t < 0.05) return mix(class_M, class_G, t * 20.0);
    if (t < 0.15) return mix(class_G, class_A, (t - 0.05) * 10.0);
    if (t < 0.35) return mix(class_A, class_B, (t - 0.15) * 5.0);
    if (t < 0.65) return mix(class_B, class_O, (t - 0.35) * 3.33);
    return mix(class_O, class_WR, (t - 0.65) * 2.85);
}

// --- ENHANCED PROCEDURAL SKYBOX ---
vec3 getSky(vec3 rd) {
    vec3 sky = vec3(0.001, 0.002, 0.005);
    
    float mw_noise = fbm(rd * 3.0);
    float mw = pow(max(0.0, mw_noise - 0.5) * 2.0, 3.0); 
    float band = smoothstep(0.4, 0.0, abs(rd.y + sin(rd.x*2.0)*0.3));
    sky += vec3(0.02, 0.04, 0.08) * mw * band * 2.0;
    
    float neb_noise = fbm(rd * 5.0 + vec3(1.2, 3.4, 5.6));
    float neb_mask = smoothstep(0.85, 1.0, neb_noise); 
    vec3 neb_col = mix(vec3(0.6, 0.1, 0.4), vec3(0.1, 0.6, 0.8), fbm(rd * 10.0));
    sky += neb_col * neb_mask * 1.5;
    
    float cluster = smoothstep(0.5, 0.9, fbm(rd * 4.0));
    vec3 p = rd * 300.0; vec3 i = floor(p); vec3 f = fract(p) - 0.5;
    float rand_val = fract(sin(dot(i, vec3(12.989, 78.233, 45.164))) * 43758.5453);
    
    float thresh = mix(0.995, 0.96, cluster); 
    if (rand_val > thresh) {
        float size = smoothstep(0.4, 0.0, length(f));
        vec3 s_col = mix(vec3(1.0, 0.7, 0.5), vec3(0.5, 0.8, 1.0), fract(rand_val * 456.123));
        sky += s_col * size * ((rand_val - thresh) / (1.0 - thresh)) * 8.0;
    }
    
    vec3 cp = rd * 100.0; vec3 ci = floor(cp); vec3 cf = fract(cp) - 0.5;
    float crand = fract(sin(dot(ci, vec3(93.189, 12.233, 67.164))) * 23758.5453);
    if (crand > 0.998) {
        float csize = smoothstep(0.3, 0.0, length(cf));
        sky += vec3(1.0, 0.95, 0.9) * pow(csize, 2.0) * 15.0;
        
        float glare = smoothstep(0.01, 0.0, abs(cf.x)) * smoothstep(0.5, 0.0, abs(cf.y)) +
                      smoothstep(0.01, 0.0, abs(cf.y)) * smoothstep(0.5, 0.0, abs(cf.x));
        sky += vec3(0.6, 0.8, 1.0) * glare * 5.0;
    }
    return sky;
}

void main() {
    vec3 ro = camera_pos; vec3 rd = normalize(world_pos - camera_pos);
    vec3 p = ro; vec3 v = rd; vec4 acc_col = vec4(0.0); 
    float dt = 0.2; bool hit_horizon = false; vec3 glow_col = vec3(0.0);

    // --- 1. LIVING STAR ---
    if (star_radius > 0.1) {
        float b = dot(ro, rd); float c = dot(ro, ro) - (star_radius * star_radius); float h = b*b - c;
        if (h > 0.0) {
            float t = -b - sqrt(h);
            if (t > 0.0) {
                vec3 hit_p = ro + rd * t;
                vec3 normal = normalize(hit_p);
                float view_angle = max(dot(normal, -rd), 0.0);
                float limb = pow(view_angle, 0.5); 
                
                float surf = fbm(hit_p * (1.0/star_radius) * 3.0 + iTime * 0.5);
                vec3 base_col = stellarColor(star_temp);
                acc_col = vec4(base_col * (0.6 + surf * 0.5) * (0.5 + limb * 0.8), 1.0);
            }
        } 
        if (acc_col.a < 1.0) {
            float miss = length(cross(rd, -ro));
            float corona = pow(smoothstep(star_radius * 2.5, star_radius, miss), 2.5);
            acc_col.rgb += stellarColor(star_temp * 0.8) * 0.8 * corona;
        }
    }

    // --- 2. THE REMNANT (WD, NS, BH) ---
    if (remnant_type > 0.0 && acc_col.a < 0.99) {
        float ISCO = remnant_radius * 3.0; 
        float disk_outer = ISCO * 10.0;
        
        for(int i = 0; i < ITERATIONS; i++) {
            float r = length(p);
            
            // A. White Dwarf
            if (remnant_type == 1.0 && r < remnant_radius) {
                vec3 normal = normalize(p);
                float surf = fbm(normal * 30.0 + iTime * 8.0) * 0.15; 
                float view_angle = max(dot(normal, -v), 0.0);
                
                float limb = pow(view_angle, 0.2); 
                float fresnel = pow(1.0 - view_angle, 5.0); 
                
                vec3 base_col = vec3(0.9, 0.95, 1.0); 
                vec3 hot_col = vec3(1.0, 1.0, 1.0);
                vec3 col = mix(base_col, hot_col, surf);
                col += vec3(0.3, 0.6, 1.0) * fresnel * 2.5; 
                
                acc_col.rgb += col * limb * (1.0 - acc_col.a);
                acc_col.a = 1.0; hit_horizon = true; break;
            }
            if (remnant_type == 1.0 && r < remnant_radius * 3.5 && acc_col.a < 1.0) {
                float dist = r / remnant_radius;
                float g = exp(-(dist - 1.0) * 4.0) * (1.0 - acc_col.a);
                glow_col += vec3(0.4, 0.7, 1.0) * g * 1.5; 
            }

            // B. Neutron Star
            if (remnant_type == 2.0) {
                float spin_speed = iTime * 40.0; 
                float tilt = 0.4; 
                vec3 mag_axis = normalize(vec3(sin(tilt)*cos(spin_speed), sin(tilt)*sin(spin_speed), cos(tilt)));

                if (r < remnant_radius) {
                    vec3 normal = normalize(p);
                    float pole_dist = abs(dot(normal, mag_axis)); 
                    vec3 rot_p = vec3(p.x * cos(spin_speed) - p.y * sin(spin_speed), p.x * sin(spin_speed) + p.y * cos(spin_speed), p.z);
                    float crust = fbm(normalize(rot_p) * 15.0);
                    float limb = pow(max(dot(normal, -v), 0.0), 0.8); 
                    vec3 base_col = mix(vec3(0.1, 0.4, 1.0), vec3(0.6, 0.8, 1.0), crust);
                    vec3 pole_col = vec3(1.0, 1.0, 1.0) * 3.0; 
                    vec3 final_surf = mix(base_col, pole_col, pow(pole_dist, 6.0));
                    acc_col.rgb += final_surf * limb * (1.0 - acc_col.a);
                    acc_col.a = 1.0; hit_horizon = true; break;
                }
                
                float cyl_d = length(p - dot(p, mag_axis) * mag_axis);
                float z_d = length(p); 
                float beam_w = remnant_radius * 0.12 + z_d * 0.03; 
                
                if (cyl_d < beam_w * 4.0 && z_d > remnant_radius && z_d < remnant_radius * 80.0) { 
                    float core_dens = pow(smoothstep(beam_w * 0.4, 0.0, cyl_d), 2.0); 
                    float corona_dens = smoothstep(beam_w * 4.0, beam_w * 0.4, cyl_d) * 0.3;
                    float pole_mask = smoothstep(0.7, 0.98, abs(dot(normalize(p), mag_axis))); 
                    float z_fade = 1.0 - smoothstep(remnant_radius * 20.0, remnant_radius * 80.0, z_d);
                    
                    vec3 p_norm = normalize(p);
                    vec3 tangent = cross(mag_axis, p_norm);
                    float helix1 = pow(max(0.0, sin(dot(tangent, vec3(1.0)) * 15.0 + z_d * 10.0 - iTime * 80.0)), 3.0);
                    float helix2 = pow(max(0.0, sin(dot(tangent, vec3(-1.0, 1.0, 0.0)) * 15.0 - z_d * 10.0 - iTime * 80.0)), 3.0);
                    
                    float plasma_noise = fbm(p * 4.0 - mag_axis * iTime * 100.0);
                    float pulse = pow(plasma_noise, 3.0) * 2.0;
                    float density = (core_dens * 4.0 + corona_dens + (helix1 + helix2) * corona_dens * 2.0) * pole_mask * z_fade;
                    
                    if (density > 0.005) {
                        vec3 beam_col = mix(vec3(0.1, 0.2, 1.0), vec3(0.8, 0.95, 1.0), core_dens);
                        beam_col *= (1.0 + pulse + max(helix1, helix2));
                        float step_a = 1.0 - exp(-density * dt * 25.0); 
                        acc_col.rgb += beam_col * step_a * (1.0 - acc_col.a);
                        acc_col.a += step_a * (1.0 - acc_col.a);
                    }
                }
            }

            // C. Black Hole
            if (remnant_type == 3.0 && r < remnant_radius) {
                vec3 horizon_hue = vec3(0.005, 0.0, 0.02); 
                acc_col.rgb = mix(acc_col.rgb, horizon_hue, 1.0 - acc_col.a);
                acc_col.a = 1.0; hit_horizon = true; break;
            }

            if (disk_alpha > 0.0 && abs(v.z) > 0.0001 && p.z * (p.z + v.z * dt) <= 0.0) {
                vec3 hit_p = p - v * (p.z / v.z); 
                float dist = length(hit_p.xy);
                
                if (dist > ISCO && dist < disk_outer) {
                    float beta = 0.5 * sqrt(ISCO / dist); 
                    vec3 gas_dir = normalize(vec3(-hit_p.y, hit_p.x, 0.0));
                    float cos_theta = dot(gas_dir, -v);
                    float gamma = 1.0 / sqrt(1.0 - beta * beta);
                    float delta = 1.0 / (gamma * (1.0 - beta * cos_theta));
                    
                    float beaming_intensity = pow(delta, 3.0); 
                    float swirl = fbm(vec3(atan(hit_p.y, hit_p.x) * 4.0 - iTime * 2.0, dist * 0.5, iTime));
                    
                    float local_temp = 25000.0 * (ISCO / dist); 
                    float observed_temp = local_temp * delta; 
                    
                    vec3 col = stellarColor(observed_temp) * beaming_intensity * (0.5 + swirl);
                    float alpha = clamp(smoothstep(disk_outer, ISCO, dist) * disk_alpha * 4.0, 0.0, 1.0);
                    
                    acc_col.rgb += col * alpha * (1.0 - acc_col.a);
                    acc_col.a += alpha * (1.0 - acc_col.a);
                    
                    if (acc_col.a > 0.99) { acc_col.a = 1.0; hit_horizon = true; break; }
                }
            }

            vec3 h = cross(p, v);
            float M_eff = 0.0;
            
            if (remnant_type == 3.0) M_eff = remnant_radius * 0.5; 
            else if (remnant_type == 2.0) M_eff = remnant_radius * 0.15; 
            else if (remnant_type == 1.0) M_eff = 0.0; 
            
            vec3 accel = -1.5 * M_eff * dot(h, h) * p / pow(r, 5.0);
            v = normalize(v + accel * dt); 
            p += v * dt;
            
            if (r > max(length(camera_pos) + 500.0, disk_outer * 2.0 + 200.0)) break; 
            dt = 0.01 + 0.05 * r; 
        }
        
        if (!hit_horizon) {
            acc_col.rgb += glow_col; 
            acc_col.rgb += getSky(v) * (1.0 - acc_col.a);
            acc_col.a = 1.0;
        }
    } 

    if (acc_col.a < 0.99 && remnant_type == 0.0) { acc_col.rgb += getSky(rd) * (1.0 - acc_col.a); }

    // --- 3. EJECTA (PHYSICS ACCURATE PLANETARY NEBULA BUBBLE) ---
    if (explosion_type == 1.0 && ejecta_intensity > 0.0 && ejecta_radius > 0.1) {
        float b = dot(ro, rd); float bounds = ejecta_radius + 15.0; 
        float c = dot(ro, ro) - (bounds * bounds); float h = b*b - c;
        
        if (h > 0.0) {
            float t1 = max(-b - sqrt(h), 0.0); float t2 = -b + sqrt(h);
            float step_size = (t2 - t1) / 40.0; float t = t1;
            vec3 wave_col = vec3(0.0); float wave_alpha = 0.0;
            
            for(int j=0; j<40; j++) {
                if (t > t2) break;
                vec3 hit_p = ro + rd * t;
                float r_dist = length(hit_p);
                
                float shell = smoothstep(ejecta_radius - 12.0, ejecta_radius, r_dist) * smoothstep(ejecta_radius + 2.0, ejecta_radius, r_dist);
                
                if (shell > 0.01) {
                    float noise_val = fbm(hit_p * 0.15 + iTime * 0.2); 
                    float density = shell * (0.2 + noise_val * 0.8) * ejecta_intensity * 0.12; 
                    
                    float color_mix = clamp((r_dist - (ejecta_radius - 10.0)) / 12.0, 0.0, 1.0);
                    vec3 col = mix(vec3(0.0, 0.8, 0.9), vec3(0.9, 0.1, 0.2), color_mix);
                    
                    wave_col += col * density * (1.0 - wave_alpha); 
                    wave_alpha += density * (1.0 - wave_alpha);
                }
                if (wave_alpha > 0.95) break; 
                t += step_size;
            }
            acc_col.rgb += wave_col * (1.0 - acc_col.a); acc_col.a += wave_alpha * (1.0 - acc_col.a);
        }
    }

    // --- PURE 3D CENTERED FLASH ---
    if (flash_intensity > 0.0) {
        float center_dist = 1.0 - max(dot(rd, normalize(-camera_pos)), 0.0);
        
        float bloom = exp(-center_dist * 60.0 / flash_intensity);
        acc_col.rgb += vec3(0.9, 0.95, 1.0) * bloom * flash_intensity * 3.5;
        
        float glow = exp(-center_dist * 12.0 / flash_intensity);
        acc_col.rgb += vec3(0.4, 0.5, 1.0) * glow * flash_intensity * 1.5;
    }

    vec3 final_col = ACESFilm(acc_col.rgb);
    final_col += (fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.54) - 0.5) * 0.02;
    fragColor = vec4(final_col, 1.0);
}
"""

# ==========================================
# 2. PYTHON APPLICATION
# ==========================================
class MasterStellarEngine(ShowBase):
    def __init__(self):
        super().__init__()
        
        self.setBackgroundColor(0, 0, 0)
        self.disableMouse() 
        self.camLens.setFar(200000.0)

        self.cam_pivot = self.render.attachNewNode("cam_pivot")
        self.cam_pivot.setPos(0, 0, 0) 
        self.camera.reparentTo(self.cam_pivot)
        
        self.base_cam_dist = 15.0
        self.zoom_mult = 1.0 
        self.cam_dist = 15.0
        
        self.last_time = 0.0
        self.sim_time = 0.0
        self.time_speed = 1.0 
        self._last_rate = 1.0

        # FIX: Ensure camera height is 0 so the angle doesn't distort on extreme zooms!
        self.camera.setPos(0, -self.cam_dist, 0) 
        self.camera.lookAt(self.cam_pivot)
        
        # FIX: Tilt the entire camera pivot by 15 degrees to get the perfect permanent accretion disk angle
        self.cam_pivot.setHpr(0, -15, 0)

        self.is_dragging_cam = False
        self.is_dragging_slider = False
        self.active_slider = None
        
        self.last_mouse_x = 0; self.last_mouse_y = 0
        self.current_mass = 1.0 

        self.active_sequence = None
        self.is_collapsed = False

        self.world = self.loader.loadModel("models/smiley")
        self.world.reparentTo(self.render)
        self.world.setScale(100000.0) 
        self.world.clearTexture()
        self.world.setTwoSided(True)
        
        self.world.node().setBounds(OmniBoundingVolume())
        self.world.node().setFinal(True)
        self.world.setBin("background", 0)
        self.world.setDepthWrite(False)

        self.rt_shader = Shader.make(Shader.SL_GLSL, VERT_SHADER, FRAG_SHADER)
        self.world.setShader(self.rt_shader)

        self.create_ui()
        self.setup_inputs()
        
        self.reset_sim()
        self.taskMgr.add(self.update_loop, "update_loop")

    def create_ui(self):
        OnscreenText(text="Star Collapse", style=1, fg=(1, 0.8, 0.2, 1), pos=(0, -0.15), scale=0.12, align=TextNode.ACenter, parent=self.a2dTopCenter)
        
        self.star_stats = OnscreenText(text="", style=1, fg=(0.8, 0.8, 0.8, 1), pos=(0.05, -0.1), scale=0.05, align=TextNode.ALeft, parent=self.a2dTopLeft)
        self.remnant_text = OnscreenText(text="", style=1, fg=(0.6, 0.8, 1.0, 1), pos=(0.05, -0.22), scale=0.05, align=TextNode.ALeft, parent=self.a2dTopLeft)
        
        self.status = OnscreenText(text="Status: Main Sequence", style=1, fg=(1, 0.8, 0.2, 1), pos=(-0.05, -0.1), scale=0.05, align=TextNode.ARight, parent=self.a2dTopRight)
        
        self.mass_text = OnscreenText(text="", style=1, fg=(1, 0.8, 0.2, 1), pos=(0, 0.15), scale=0.06, align=TextNode.ACenter, parent=self.a2dBottomCenter)
        
        self.mass_slider = DirectSlider(
            range=(0.8, 300.0), value=self.current_mass, pageSize=0, 
            pos=(0, 0, 0.08), scale=0.4, parent=self.a2dBottomCenter,
            frameSize=(-1.0, 1.0, -0.06, 0.06), 
            thumb_frameSize=(-0.05, 0.05, -0.12, 0.12), 
            state=DGG.DISABLED
        )
        self.mass_slider['frameColor'] = (0.3, 0.3, 0.3, 1.0)
        self.mass_slider.thumb['frameColor'] = (0.9, 0.9, 0.9, 1.0)

        OnscreenText(text="[SPACE] - Trigger Life Cycle", style=1, fg=(0.5, 1, 0.5, 1), pos=(0.05, 0.25), scale=0.05, align=TextNode.ALeft, parent=self.a2dBottomLeft)
        OnscreenText(text="[ R ] - Reset Universe", style=1, fg=(1, 0.5, 0.5, 1), pos=(0.05, 0.15), scale=0.05, align=TextNode.ALeft, parent=self.a2dBottomLeft)
        OnscreenText(text="[ T ] - Reset Time Speed", style=1, fg=(0.5, 0.8, 1.0, 1), pos=(0.05, 0.05), scale=0.05, align=TextNode.ALeft, parent=self.a2dBottomLeft)
        
        self.speed_text = OnscreenText(text="Time Speed: 1.00x", style=1, fg=(0.5, 1.0, 0.8, 1), pos=(-0.05, 0.15), scale=0.05, align=TextNode.ARight, parent=self.a2dBottomRight)
        
        self.speed_slider = DirectSlider(
            range=(0.01, 5.0), value=self.time_speed, pageSize=0, 
            pos=(-0.35, 0, 0.08), scale=0.3, parent=self.a2dBottomRight,
            frameSize=(-1.0, 1.0, -0.06, 0.06), 
            thumb_frameSize=(-0.05, 0.05, -0.12, 0.12), 
            state=DGG.DISABLED
        )
        self.speed_slider['frameColor'] = (0.3, 0.3, 0.3, 1.0)
        self.speed_slider.thumb['frameColor'] = (0.9, 0.9, 0.9, 1.0)
        
        self.on_slider_update()

    def get_real_mass(self):
        return self.current_mass

    def on_speed_update(self):
        if not hasattr(self, 'speed_slider'): return
        self.time_speed = max(0.01, self.speed_slider['value'])
        self.speed_text.setText(f"Time Speed: {self.time_speed:.2f}x")
        
        if hasattr(self, 'active_sequence') and self.active_sequence and self.active_sequence.isPlaying():
            if abs(self._last_rate - self.time_speed) > 0.2:
                self.active_sequence.setPlayRate(self.time_speed)
                self._last_rate = self.time_speed

    def reset_time_speed(self):
        self.time_speed = 1.0
        self.speed_slider['value'] = 1.0
        self.speed_text.setText("Time Speed: 1.00x")
        if hasattr(self, 'active_sequence') and self.active_sequence and self.active_sequence.isPlaying():
            self.active_sequence.setPlayRate(self.time_speed)
            self._last_rate = self.time_speed

    def calculate_star_temp(self, mass):
        data = [
            (0.8, 5000), (1.0, 5800), (1.5, 7000), (2.0, 9000),
            (5.0, 15000), (15.0, 28000), (30.0, 38000), (50.0, 42000),
            (150.0, 50666), (300.0, 52833)
        ]
        if mass <= data[0][0]: return data[0][1]
        if mass >= data[-1][0]: return data[-1][1]
        for i in range(len(data) - 1):
            m1, t1 = data[i]
            m2, t2 = data[i+1]
            if m1 <= mass <= m2:
                fraction = (mass - m1) / (m2 - m1)
                return t1 + fraction * (t2 - t1)
        return 5800 

    def calculate_remnant_mass(self, M):
        if M < 8.2:
            if M < 2.85: return 0.08 * M + 0.489
            elif M <= 3.59: return 0.187 * M + 0.184
            else: return 0.107 * M + 0.471
        elif M <= 25.0:
            return min(2.2, 1.1 + (M - 8.2) / 16.8 * 1.4)
        return None 

    def on_slider_update(self):
        if not hasattr(self, 'mass_slider') or not hasattr(self, 'is_collapsed'): return
        
        if self.is_collapsed:
            next_mass = self.mass_slider['value']
            self.mass_text.setText(f"Queued Mass: {next_mass:.1f} M_Sun (Press R to Reset)")
            return
            
        self.current_mass = self.mass_slider['value']
        M = self.get_real_mass()
        self.mass_text.setText(f"Initial Mass: {M:.1f} M_Sun")
        
        temp = self.calculate_star_temp(M)
        
        if M < 8.2:
            radius = 2.0 + M * 0.5
            s_type = "Yellow/White Dwarf"
        elif M < 150:
            radius = 6.1 + math.pow(M - 8.2, 0.5) * 1.5 
            if M > 80: s_type = "Wolf-Rayet / Blue Hypergiant"
            elif M > 25: s_type = "Blue Supergiant"
            else: s_type = "Blue/White Giant"
        else:
            radius = 23.96 + (M - 150) * 0.1
            s_type = "Ultra-Massive O-Type Hypergiant"
        
        self.star_stats.setText(f"Type: {s_type}\nTemp: {int(temp)}K")
        self.world.setShaderInput("star_radius", radius)
        self.world.setShaderInput("star_temp", temp)
        
        if M < 8.2:
            r_mass = self.calculate_remnant_mass(M)
            self.remnant_text.setText(f"Destiny: White Dwarf ({r_mass:.2f} M_Sun)")
        elif M <= 25.0:
            r_mass = self.calculate_remnant_mass(M)
            self.remnant_text.setText(f"Destiny: Neutron Star (~{r_mass:.2f} M_Sun)")
        else:
            M_co = (0.773 * (0.1 * (M ** 1.4))) - 0.35
            dM = M - (0.1 * (M ** 1.4))
            M_f = M - dM
            f = (M_co - 2.5) / 3.5 if M_co < 6 else 1.0
            M_Bh = 1 + (f * (M_f - 1))
            if M < 150:
                self.remnant_text.setText(f"Destiny: Stellar Black Hole ({M_Bh:.2f} M_Sun)")
            else:
                self.remnant_text.setText(f"Destiny: Direct Collapse Black Hole ({M_Bh:.2f} M_Sun)")

    def setup_inputs(self):
        self.accept("space", self.start_sim)
        self.accept("r", self.reset_sim)
        self.accept("t", self.reset_time_speed) 
        self.accept("escape", sys.exit)
        self.accept("mouse1", self.start_drag)
        self.accept("mouse1-up", self.stop_drag)
        self.accept("wheel_up", self.zoom, [-1.0])
        self.accept("wheel_down", self.zoom, [1.0])

    def start_drag(self):
        if not self.mouseWatcherNode.hasMouse(): return
        x = self.mouseWatcherNode.getMouseX()
        y = self.mouseWatcherNode.getMouseY()
        p2d = Point3(x, 0, y)

        loc_m = self.mass_slider.getRelativePoint(self.render2d, p2d)
        if -1.1 <= loc_m.getX() <= 1.1 and -0.5 <= loc_m.getZ() <= 0.5:
            self.active_slider = self.mass_slider
            self.taskMgr.add(self.slider_drag_task, "slider_drag_task")
            return

        loc_s = self.speed_slider.getRelativePoint(self.render2d, p2d)
        if -1.1 <= loc_s.getX() <= 1.1 and -0.5 <= loc_s.getZ() <= 0.5:
            self.active_slider = self.speed_slider
            self.taskMgr.add(self.slider_drag_task, "slider_drag_task")
            return

        if y < 0.5:
            self.is_dragging_cam = True
            self.last_mouse_x = x
            self.last_mouse_y = y

    def slider_drag_task(self, task):
        if not self.active_slider or not self.mouseWatcherNode.hasMouse():
            return task.done
        
        x = self.mouseWatcherNode.getMouseX()
        y = self.mouseWatcherNode.getMouseY()
        
        loc = self.active_slider.getRelativePoint(self.render2d, Point3(x, 0, y))
        ratio = (loc.getX() + 1.0) / 2.0
        ratio = max(0.0, min(1.0, ratio)) 

        min_val, max_val = self.active_slider['range']
        self.active_slider['value'] = min_val + ratio * (max_val - min_val)
        
        if self.active_slider == self.mass_slider:
            self.on_slider_update()
        elif self.active_slider == self.speed_slider:
            self.on_speed_update()
            
        return task.cont

    def stop_drag(self): 
        self.is_dragging_cam = False
        self.active_slider = None
        self.taskMgr.remove("slider_drag_task")

    def zoom(self, direction):
        if direction < 0: self.zoom_mult *= 0.85
        else: self.zoom_mult *= 1.15
        self.zoom_mult = max(0.01, min(100.0, self.zoom_mult))

    def reset_sim(self):
        if self.active_sequence: self.active_sequence.finish()
        self.is_collapsed = False
        self.zoom_mult = 1.0
        self.status.setText("Status: Main Sequence")
        self.status.setFg((1, 0.8, 0.2, 1))

        self.world.setShaderInput("remnant_type", 0.0) 
        self.world.setShaderInput("remnant_mass", 0.0) 
        self.world.setShaderInput("remnant_radius", 0.0) 
        self.world.setShaderInput("explosion_type", 0.0)
        self.world.setShaderInput("ejecta_intensity", 0.0)
        self.world.setShaderInput("ejecta_radius", 0.0)
        self.world.setShaderInput("flash_intensity", 0.0)
        self.world.setShaderInput("disk_alpha", 0.0)
        
        # Reset camera angle lock
        self.cam_pivot.setHpr(0, -15, 0)
        self.on_slider_update() 

    def start_sim(self):
        if self.is_collapsed: return
        self.is_collapsed = True
        
        M = self.get_real_mass()
        init_rad = self.world.getShaderInput("star_radius").getVector()[0]
        init_temp = self.world.getShaderInput("star_temp").getVector()[0]
        
        # ==========================================
        # PATH 1: WHITE DWARF (< 8.2 M)
        # ==========================================
        if M < 8.2:
            r_type = 1.0
            r_mass = self.calculate_remnant_mass(M)
            r_rad = 0.2
            
            expand = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad, toData=18.0, duration=3.0, blendType='easeIn')
            pulse1_down = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=18.0, toData=15.0, duration=0.6, blendType='easeInOut')
            pulse1_up   = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=15.0, toData=19.0, duration=0.5, blendType='easeInOut')
            
            shed_core = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=19.0, toData=0.0, duration=0.5, blendType='easeIn')
            flash_up = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=0.0, toData=1.5, duration=0.2)
            flash_down = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=1.5, toData=0.0, duration=3.0)

            def trigger():
                self.world.setShaderInput("star_radius", 0.0) 
                self.world.setShaderInput("remnant_type", r_type); self.world.setShaderInput("remnant_mass", r_mass); self.world.setShaderInput("remnant_radius", r_rad) 
                self.world.setShaderInput("explosion_type", 1.0) 
                self.status.setText("Status: White Dwarf & Planetary Nebula"); self.status.setFg((0.7, 0.85, 1.0, 1))

            neb_rad = LerpFunc(lambda v: self.world.setShaderInput("ejecta_radius", v), fromData=2.0, toData=80.0, duration=15.0)
            neb_up = LerpFunc(lambda v: self.world.setShaderInput("ejecta_intensity", v), fromData=0.0, toData=1.5, duration=2.0)
            neb_down = LerpFunc(lambda v: self.world.setShaderInput("ejecta_intensity", v), fromData=1.5, toData=0.0, duration=13.0)

            self.active_sequence = Sequence(
                Func(self.status.setText, "Status: Red Giant Expansion"), expand,
                Func(self.status.setText, "Status: Thermal Pulses"), pulse1_down, pulse1_up,
                Func(self.status.setText, "Status: Envelope Ejection"), Parallel(shed_core, flash_up), Func(trigger), 
                Parallel(flash_down, neb_rad, Sequence(neb_up, neb_down))
            )
            
        # ==========================================
        # PATH 2: CORE COLLAPSE (8.2 to 150 M)
        # ==========================================
        elif M <= 150:
            if M <= 25: 
                r_type = 2.0 
                r_mass = self.calculate_remnant_mass(M)
                r_rad = 0.05 
            else: 
                r_type = 3.0
                M_co = (0.773 * (0.1 * (M ** 1.4))) - 0.35
                dM = M - (0.1 * (M ** 1.4))
                M_f = M - dM
                f = (M_co - 2.5) / 3.5 if M_co < 6 else 1.0
                r_mass = 1 + (f * (M_f - 1))
                r_rad = 0.1 + (r_mass * 0.01) 
            
            sg_temp = 3500.0

            expand = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad, toData=init_rad*3.0, duration=3.0, blendType='easeIn')
            cool_temp = LerpFunc(lambda v: self.world.setShaderInput("star_temp", v), fromData=init_temp, toData=sg_temp, duration=3.0, blendType='easeIn')
            
            trem_down = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad*3.0, toData=init_rad*2.9, duration=0.1, blendType='easeInOut')
            trem_up = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad*2.9, toData=init_rad*3.0, duration=0.1, blendType='easeInOut')
            implode = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad*3.0, toData=0.0, duration=0.15, blendType='easeIn')
            
            flash_up = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=0.0, toData=5.0, duration=0.1)
            flash_down = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=5.0, toData=0.0, duration=2.5)

            def trigger():
                self.world.setShaderInput("remnant_type", r_type); self.world.setShaderInput("remnant_mass", r_mass); self.world.setShaderInput("remnant_radius", r_rad) 
                self.world.setShaderInput("explosion_type", 0.0) 
                name = "Black Hole" if r_type == 3.0 else "Neutron Star"
                self.status.setText(f"Status: Core Collapse ({name})"); self.status.setFg((0.7, 0.85, 1.0, 1))

            disk_fade = LerpFunc(lambda v: self.world.setShaderInput("disk_alpha", v), fromData=0.0, toData=(1.0 if r_type==3.0 else 0.0), duration=4.0)

            self.active_sequence = Sequence(
                Func(self.status.setText, "Status: Supergiant Expansion"), Parallel(expand, cool_temp),
                Func(self.status.setText, "Status: Core Instability"), Sequence(trem_down, trem_up, trem_down, trem_up),
                Func(self.status.setText, "Status: CORE COLLAPSE!"), implode, flash_up, Func(trigger),
                Parallel(flash_down, Sequence(Wait(2.5), disk_fade))
            )

        # ==========================================
        # PATH 3: DIRECT COLLAPSE (> 150 M)
        # ==========================================
        else:
            r_type = 3.0
            M_co = (0.773 * (0.1 * (M ** 1.4))) - 0.35
            dM = M - (0.1 * (M ** 1.4))
            M_f = M - dM
            f = (M_co - 2.5) / 3.5 if M_co < 6 else 1.0
            r_mass = 1 + (f * (M_f - 1))
            r_rad = 0.2 + (r_mass * 0.01) 
            
            collapse = LerpFunc(lambda v: self.world.setShaderInput("star_radius", v), fromData=init_rad, toData=0.0, duration=1.5, blendType='easeIn')
            redshift = LerpFunc(lambda v: self.world.setShaderInput("star_temp", v), fromData=init_temp, toData=1200.0, duration=1.2, blendType='easeIn')
            
            flash_up = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=0.0, toData=2.0, duration=0.15)
            flash_down = LerpFunc(lambda v: self.world.setShaderInput("flash_intensity", v), fromData=2.0, toData=0.0, duration=2.0)
            
            def trigger():
                self.world.setShaderInput("remnant_type", r_type); self.world.setShaderInput("remnant_mass", r_mass); self.world.setShaderInput("remnant_radius", r_rad) 
                self.world.setShaderInput("explosion_type", 0.0) 
                self.status.setText(f"Status: Direct Collapse Black Hole"); self.status.setFg((0.4, 0.2, 1.0, 1))

            disk_ignite = LerpFunc(lambda v: self.world.setShaderInput("disk_alpha", v), fromData=0.0, toData=1.0, duration=4.0)

            self.active_sequence = Sequence(
                Func(self.status.setText, "Status: DIRECT COLLAPSE INITIATED..."), Parallel(collapse, redshift), flash_up, Func(trigger),
                Parallel(flash_down, disk_ignite)
            )
            
        self.active_sequence.setPlayRate(self.time_speed)
        self.active_sequence.start()

    def update_loop(self, task):
        dt = task.time - self.last_time
        self.last_time = task.time
        self.sim_time += dt * self.time_speed

        if self.mouseWatcherNode.hasMouse():
            if getattr(self, 'is_dragging_cam', False):
                x = self.mouseWatcherNode.getMouseX()
                y = self.mouseWatcherNode.getMouseY()
                dx = x - self.last_mouse_x; dy = y - self.last_mouse_y
                self.cam_pivot.setH(self.cam_pivot.getH() - dx * 100)
                self.cam_pivot.setP(max(-80, min(80, self.cam_pivot.getP() + dy * 100))) 
                self.last_mouse_x = x; self.last_mouse_y = y

        current_star_r = self.world.getShaderInput("star_radius").getVector()[0]
        rem_type = self.world.getShaderInput("remnant_type").getVector()[0]
        rem_rad = self.world.getShaderInput("remnant_radius").getVector()[0]

        ideal_dist = 12.0 
        if current_star_r > 0.1: ideal_dist = max(ideal_dist, current_star_r * 4.0)
        
        if current_star_r <= 0.1: 
            # FIX: Black hole zoom is calculated smoothly as 1.5x away from the 30.0 accretion disk radius
            if rem_type == 3.0: ideal_dist = max(5.0, rem_rad * 45.0) 
            if rem_type == 1.0 or rem_type == 2.0: ideal_dist = max(5.0, rem_rad * 40.0)

        self.base_cam_dist += (ideal_dist - self.base_cam_dist) * dt * 3.0
        self.cam_dist = self.base_cam_dist * self.zoom_mult
        
        # FIX: Ensure camera height is 0 so the angle doesn't distort on extreme zooms!
        self.camera.setPos(0, -self.cam_dist, 0) 
        self.camera.lookAt(self.cam_pivot)

        self.world.setShaderInput("camera_pos", self.camera.getPos(self.render))
        self.world.setShaderInput("iTime", self.sim_time)
        return task.cont

if __name__ == "__main__":
    app = MasterStellarEngine()
    app.run()
