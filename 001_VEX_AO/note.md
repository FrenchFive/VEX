# 🌟 VEX AO: Ambient Occlusion Mask 🌟

This VEX code generates a **Mask for Ambient Occlusion (AO)** by sampling the geometry using rays. The script allows you to customize the resolution of ray sampling, computes occlusion, and outputs a `@mask` attribute. Additionally, it visualizes the occlusion effect with the `@Cd` attribute.

VERY SLOW but Clean.

---

## 📝 **Key Features**
- **✨ Adjustable Resolution:** Define the number of vertical and horizontal ray samples.
- **🎯 Accurate Hit Detection:** Rays detect intersections and calculate occlusion.
- **📊 Output Attributes:**
  - `@mask`: Stores the AO value.
  - `@Cd`: Visualizes AO as a color.

---

## 📋 **Code Parameters**
| **Parameter**   | **Description**                                   |
|------------------|---------------------------------------------------|
| `RESVert`        | Number of vertical slices (resolution for θ).     |
| `maxdist`        | Maximum ray distance for detecting hits.          |
| `bias`           | Small offset to avoid self-intersection.          |


---

## 🛠️ **How It Works**
1. **Sampling Rays:**  
   Rays are sampled in a hemispherical distribution around the surface normal.  
   - `θ (theta)`: Vertical angle (polar).
   - `φ (phi)`: Horizontal angle (azimuthal).
2. **Intersection Detection:**  
   Each ray is traced into the scene, and intersections within `maxdist` are accumulated.  
3. **Occlusion Calculation:**  
   Occlusion (`occ`) is normalized by the total number of samples, ensuring values range from `0` (no occlusion) to `1` (fully occluded).  
4. **Output:**  
   - `@mask`: Used for further computation.
   - `@Cd`: Directly visualizes AO as a grayscale color.

---

## 🎨 **Example Usage**
1. Add a **Parameter** node to your geometry and set `RESVert` for resolution control.  
2. Apply the VEX code in a **Wrangle Node**.  
3. Visualize the AO effect in the viewport using `@Cd`.  

---

### 🚀 **Customize and Experiment!**
- 🎯 Adjust `RESVert` for finer or coarser ray sampling.
- 🔭 Modify `maxdist` to control the occlusion range.
- ⚙️ Experiment with different geometries and see how AO adapts.

🖌️ **Bring depth and realism to your projects with Ambient Occlusion!**